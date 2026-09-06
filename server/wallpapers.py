"""壁紙の一覧と切り替え（2026-09-05、本人の指定）。

「壁紙かえたい」と言うと1段目のカードが横スクロールのスライダーになり、
タップするとPCの壁紙が実際に変わる。変わったら元のカードへ戻る。

切り替えは `caelestia wallpaper -f <ファイル>` に任せる。**自分で貼り替えない。**
caelestia は壁紙から配色（scheme.json）も作り直すので、そこへ相乗りすると
「壁紙が変わると画面の色も変わる」が今の仕組みのまま動く（app.py の
watch_scheme が両方を見張って配信済み）。

サムネイルは実物から作って配る。元は数MBあるので、そのままは配らない
（2026-08-29 に2枚 6.3MB で初回表示が固まった事故がある）。
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("uvicorn.error")

# 探す場所。日本語ロケールの「画像」と英語の「Pictures」が両方あるので両方見る。
# **Vault は探さない。** ここは PC の見た目の話で、判断の記録とは関係がない
SEARCH_DIRS = (
    Path.home() / "画像/Wallpapers",
    Path.home() / "Pictures/Wallpapers",
)
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# スライダーに出すサムネ。横スクロールで並べるので小さくてよい。
# 85枚を一度に配ることになるため、1枚を軽くすることが効く
THUMB_MAX = 320
THUMB_QUALITY = 65
# 一覧の上限。これ以上あっても指で探せない
MAX_ITEMS = 120

# caelestia が今出している壁紙。配色と同じタイミングで書き換わる
CURRENT_PATH = Path.home() / ".local/state/caelestia/wallpaper/path.txt"
# 変換済みの置き場。元は数MBのこともあるので、そのままは配らない
CACHE = Path.home() / ".cache/jarvis-secretary"
CURRENT_MAX = 1400          # 長辺。iPhone で見るには十分で、転送量を抑えられる
CURRENT_QUALITY = 72
APPLY_RETRY_DELAY = 0.8


def _identifier(path: Path) -> str:
    """パスそのものをURLに出さないための札（DESIGN の「Vault 外へ出さない」に倣う）。

    受け取った札から元のパスへ戻すのではなく、**一覧を作り直して突き合わせる**。
    こうしておくと、任意のパスを送りつけられても選択肢の外は選べない
    （パストラバーサルの口を作らない）。
    """
    return hashlib.sha256(str(path).encode()).hexdigest()[:16]


def find_all() -> list[tuple[str, Path]]:
    """選べる壁紙を (札, パス) で返す。名前順にして、並びが毎回変わらないようにする。"""
    found: list[Path] = []
    for directory in SEARCH_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUFFIXES:
                found.append(path)
    # 同じ画像が両方のフォルダにあることがある（過去に重複を整理した経緯あり）。
    # 実体で重複を落とす
    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []
    for path in found:
        try:
            key = f"{path.stat().st_size}:{path.name.lower()}"
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append((_identifier(path), path))
    return unique[:MAX_ITEMS]


def resolve(identifier: str) -> Path | None:
    """札から実体を引く。**一覧に無いものは選べない。**"""
    for candidate, path in find_all():
        if candidate == identifier:
            return path
    return None


def thumbnail(path: Path, cache: Path) -> Path | None:
    """サムネイルを作って返す。同じものがあれば作り直さない。"""
    cache.mkdir(parents=True, exist_ok=True)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    version = hashlib.sha256(f"{path}:{stamp}:{THUMB_MAX}".encode()).hexdigest()[:16]
    out = cache / f"thumb-{version}.webp"
    if out.is_file():
        return out
    try:
        subprocess.run(
            ["magick", str(path), "-auto-orient",
             "-resize", f"{THUMB_MAX}x{THUMB_MAX}>",
             "-quality", str(THUMB_QUALITY), str(out)],
            check=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out if out.is_file() else None


async def _apply_once(path: Path) -> tuple[bool, str]:
    """caelestia を1回呼び、成否と診断用のエラーを返す。"""
    process = None
    command_path = path
    # caelestia は画像の中身が正常でも、大文字の .JPG を無効扱いにする。
    # 元ファイルは変更せず、実行用キャッシュだけ小文字の拡張子に揃える。
    if path.suffix != path.suffix.lower():
        normalized_dir = CACHE / "normalized"
        normalized_dir.mkdir(parents=True, exist_ok=True)
        command_path = normalized_dir / f"{_identifier(path)}{path.suffix.lower()}"
        try:
            if not command_path.is_file() or command_path.stat().st_mtime_ns < path.stat().st_mtime_ns:
                shutil.copy2(path, command_path)
        except OSError as error:
            return False, f"could not prepare normalized image: {error}"
    try:
        process = await asyncio.create_subprocess_exec(
            "caelestia", "wallpaper", "-f", str(command_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        if process is not None:
            process.kill()
            with suppress(Exception):
                await process.communicate()
        return False, "timed out after 30s"
    except OSError as error:
        return False, str(error)
    detail = (stderr or b"").decode("utf-8", "ignore").strip()
    return process.returncode == 0, detail


async def apply(path: Path) -> bool:
    """PC の壁紙を実際に切り替える。成功したら True。

    配色の作り直しも caelestia がやる。こちらは結果を待つだけで、
    画面への反映は app.py の watch_scheme が拾って配る。
    """
    last_error = ""
    for attempt in range(2):
        ok, last_error = await _apply_once(path)
        if ok:
            logger.info("[PAPER] switched to %s%s", path.name,
                        " after retry" if attempt else "")
            return True
        if attempt == 0:
            logger.warning("[PAPER] %s failed once; retrying", path.name)
            await asyncio.sleep(APPLY_RETRY_DELAY)
    logger.warning("[PAPER] %s failed: %s", path.name, last_error[-1200:])
    return False


# --- 今出ている壁紙（背景として iPhone へ配るぶん）------------------------


def current_source() -> Path | None:
    """caelestia が今出している壁紙の実体パス。読めなければ None。"""
    try:
        raw = CURRENT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    source = Path(raw)
    return source if source.is_file() else None


def current_version(source: Path | None) -> str:
    """壁紙が変わったことを一意に表す札。パスと更新時刻から作る。"""
    if source is None:
        return ""
    try:
        stamp = source.stat().st_mtime_ns
    except OSError:
        return ""
    return hashlib.sha256(f"{source}:{stamp}".encode()).hexdigest()[:16]


def current_webp(source: Path | None, version: str) -> Path | None:
    """壁紙を iPhone 向けの WebP に落として返す。同じ版があれば作り直さない。

    元は数MBになることがある。PNG のまま置いて初回表示が固まった事故があるので
    （2026-08-29、2枚で 6.3MB）、必ず縮めてから配る。
    """
    if source is None or not version:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"wallpaper-{version}.webp"
    if out.is_file():
        return out
    try:
        subprocess.run(
            ["magick", str(source), "-auto-orient",
             "-resize", f"{CURRENT_MAX}x{CURRENT_MAX}>",
             "-quality", str(CURRENT_QUALITY), str(out)],
            check=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # 古い版を片付ける（壁紙を変えるたびに溜まるため）
    for stale in CACHE.glob("wallpaper-*.webp"):
        if stale != out:
            with suppress(OSError):
                stale.unlink()
    return out if out.is_file() else None
