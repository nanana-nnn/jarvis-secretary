"""作業が見える常駐ブラウザ（2026-09-05、本人の指定）。

常駐ターミナル（server/terminal.py）と同じ扱いで、**ブラウザも開いたままにする。**
「話しかける→PCの画面でブラウザが勝手に動く→結果だけスマホに返る」を見せるのが
目的なので、ヘッドレスにしない。終わってもウィンドウを閉じない。

**普段の Chrome は触らない。** 専用プロファイル（PROFILE_DIR）で開く。
noteのログインはこのプロファイルの中にだけ残るので、失敗しても日常の環境に
影響しない（2026-09-05、本人の選択）。ログインは最初の1回だけ本人が手で行う。

ここに note 固有の知識は持たない（それは server/note_draft.py）。
このモジュールが持つのは「1枚のブラウザを開いたまま保つ」ことだけ。
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
import os
from pathlib import Path
import subprocess

logger = logging.getLogger("uvicorn.error")

# 専用プロファイルの置き場。caelestia の scheme.json と同じ ~/.local/state 配下に置く
PROFILE_DIR = Path(
    os.getenv("BROWSER_PROFILE_DIR")
    or Path.home() / ".local/state/jarvis-secretary/browser-profile"
)

# 実体は既に入っている Google Chrome を使う（channel="chrome"）。
# Playwright 同梱の Chromium を落とすと 150MB 増えるうえ、note のような
# 商用サイトは Chrome のほうが素直に動く。プロファイルだけ分ければ
# 「普段の Chrome を触らない」は満たせる
CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")

# 画面に見せるための起動引数。自動操作である旨のバーは消さない
# （消すと「本人が操作している」ように見えてしまう。見せるのが目的なので残す）。
#
# **`--start-maximized` は使わない。** Wayland(Hyprland)では効かず、Chrome が
# 物理ピクセルの寸法でウィンドウを開いて画面からはみ出す
# （2026-09-05、実機で「画面が半分切れる」。1920x1200 の scale 1.2 ＝ 論理 1600x1000
# なのに、それより大きく開いていた）。実寸を見て明示指定する
LAUNCH_ARGS: tuple[str, ...] = ()

# 画面の縁からの余白（論理px）。ぴったりにすると縁が画面外へ出る
WINDOW_MARGIN = 24


def screen_size() -> tuple[int, int] | None:
    """今のモニタの**論理**解像度。取れなければ None（既定の大きさに任せる）。

    Hyprland は物理解像度と scale を別々に持つ。Chrome が受け取る
    `--window-size` は論理ピクセルなので、scale で割った値を渡す。
    """
    try:
        monitors = json.loads(
            subprocess.run(["hyprctl", "monitors", "-j"],
                           capture_output=True, text=True, timeout=3, check=True).stdout
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    for monitor in monitors:
        if monitor.get("focused", True):
            scale = float(monitor.get("scale") or 1) or 1
            return int(monitor["width"] / scale), int(monitor["height"] / scale)
    return None


def _chrome_pids(profile: Path) -> set[int]:
    """このプロファイルで動いている Chrome の PID。ウィンドウを見分けるのに使う
    （普段の Chrome も同時に開いている。そちらを動かしてはいけない）。"""
    pids: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().decode("utf-8", "ignore")
        except OSError:
            continue
        if f"--user-data-dir={profile}" in cmdline:
            pids.add(int(entry.name))
    return pids


def _dispatch(expression: str) -> None:
    """Hyprland へ Lua のディスパッチャを1つ送る。失敗しても黙って進む。"""
    with suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["hyprctl", "dispatch", expression],
                       capture_output=True, timeout=3, check=False)


def fit_window(profile: Path) -> bool:
    """開いたウィンドウを画面いっぱい（余白つき）に置く。

    **Chrome の起動引数ではできない。** Wayland では `--window-position` も
    `--window-size` も無視され、置き場所はコンポジタが決める
    （2026-09-05、実機。タイル半分に収まって note のエディタが右で切れた）。

    Hyprland 0.56 は Lua のディスパッチャを使う
    （`hyprctl dispatch setfloating address:...` は構文エラーになる）。
    **float は切り替えなので、既に浮いているウィンドウには送らない**
    （2回送って元へ戻り、効いていないように見えた）。

    Hyprland でなければ何もしない。普段の Chrome のウィンドウには触らない
    （このプロファイルで動いている PID のものだけを名指しする）。
    """
    size = screen_size()
    pids = _chrome_pids(profile)
    if size is None or not pids:
        return False
    try:
        clients = json.loads(
            subprocess.run(["hyprctl", "clients", "-j"],
                           capture_output=True, text=True, timeout=3, check=True).stdout
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False

    width, height = size
    target_w, target_h = width - WINDOW_MARGIN * 2, height - WINDOW_MARGIN * 2
    moved = False
    for client in clients:
        if client.get("pid") not in pids:
            continue
        window = f'{{window="address:{client["address"]}"'
        if not client.get("floating"):
            _dispatch(f"hl.dsp.window.float({window}}})")
        _dispatch(f"hl.dsp.window.resize({window}, x={target_w}, y={target_h}, exact=true}})")
        _dispatch(f"hl.dsp.window.move({window}, x={WINDOW_MARGIN}, y={WINDOW_MARGIN}, exact=true}})")
        moved = True
    return moved


class VisibleBrowser:
    """専用プロファイルのブラウザ1枚。開いたまま保つ。

    `page()` を呼ぶと、開いていなければ開き、使い回すタブを返す。
    **閉じるのは close() を呼んだときだけ。** ジョブが終わっても閉じない。
    """

    def __init__(self, profile_dir: Path | None = None, channel: str | None = None) -> None:
        self.profile_dir = profile_dir or PROFILE_DIR
        self.channel = channel or CHANNEL
        self._playwright = None
        self._context = None
        self._lock = asyncio.Lock()

    def alive(self) -> bool:
        return self._context is not None

    async def context(self):
        """開いていなければ開く。**1枚しか開かない**（terminal と同じ約束）。"""
        async with self._lock:
            if self._context is not None:
                return self._context
            from playwright.async_api import async_playwright

            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                channel=self.channel,
                headless=False,                 # **見せるのが目的**（本人の指定）
                args=list(LAUNCH_ARGS),
                # サンドボックスを切ると「サポートされていないコマンドライン
                # フラグ --no-sandbox を使用しています」の黄色い帯が出る。
                # 画面に映るのが目的なので、帯を出さない側にする
                chromium_sandbox=True,
                viewport=None,                  # ウィンドウの実寸に従わせる
                locale="ja-JP",
            )
            # ブラウザ側から閉じられたら、次の依頼で開き直せるように忘れる
            self._context.on("close", lambda _: self._forget())
            logger.info("[BROWSER] opened (profile=%s)", self.profile_dir)
            # ウィンドウが出てから位置と大きさを直す（起動引数では効かない）
            await asyncio.sleep(1.2)
            if fit_window(self.profile_dir):
                logger.info("[BROWSER] window fitted to screen")
            return self._context

    def _forget(self) -> None:
        logger.info("[BROWSER] closed by user")
        self._context = None

    async def page(self):
        """使い回すタブ。既にあるタブの1枚目を使い、無ければ作る。"""
        context = await self.context()
        pages = [page for page in context.pages if not page.is_closed()]
        return pages[0] if pages else await context.new_page()

    async def close(self) -> None:
        with suppress(Exception):
            if self._context is not None:
                await self._context.close()
        with suppress(Exception):
            if self._playwright is not None:
                await self._playwright.stop()
        self._context = None
        self._playwright = None
