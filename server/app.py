import asyncio
from contextlib import asynccontextmanager, suppress
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import platform
import pwd
import re
import socket as system_socket
import subprocess
from time import monotonic_ns

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .audio import SpeechSplitter
from .config import Settings
from .transcribe import Transcriber


logger = logging.getLogger("uvicorn.error")
DEFAULT_SCHEME_PATH = Path.home() / ".local/state/caelestia/scheme.json"
# caelestia が今出している壁紙。配色と同じタイミングで書き換わる
DEFAULT_WALLPAPER_PATH = Path.home() / ".local/state/caelestia/wallpaper/path.txt"
# 変換済みの置き場。元は数MBのこともあるので、そのままは配らない
WALLPAPER_CACHE = Path.home() / ".cache/jarvis-secretary"
WALLPAPER_MAX = 1400          # 長辺。iPhone で見るには十分で、転送量を抑えられる
WALLPAPER_QUALITY = 72
# 判断・記録の正本（AI_RULES.md の Vault）。VAULT_PATH で差し替えられる
DEFAULT_VAULT_PATH = Path(os.getenv("VAULT_PATH") or Path.home() / "ドキュメント/Start Vault")
HEX_COLOUR = re.compile(r"^[0-9a-fA-F]{6}$")
SCHEME_KEYS = (
    "background",
    "surfaceContainer",
    "surfaceContainerHigh",
    "onSurface",
    "onSurfaceVariant",
    "outlineVariant",
    "primary",
    "onPrimary",
    "error",
)


def timestamp_ms() -> int:
    return monotonic_ns() // 1_000_000


def read_primary(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["colours"]["primary"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return f"#{value.lower()}" if isinstance(value, str) and HEX_COLOUR.fullmatch(value) else None


def read_scheme(path: Path) -> dict[str, str] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        colours = payload["colours"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None

    mode = payload.get("mode")
    if mode not in {"light", "dark"}:
        return None

    scheme = {"mode": mode}
    for key in SCHEME_KEYS:
        value = colours.get(key)
        if not isinstance(value, str) or not HEX_COLOUR.fullmatch(value):
            return None
        scheme[key] = f"#{value.lower()}"
    return scheme


def scheme_event(path: Path) -> dict[str, object]:
    return {"type": "scheme.changed", "scheme": read_scheme(path), "ts": timestamp_ms()}


def format_uptime(seconds: float) -> str:
    """fastfetch と同じ「9 hours, 55 minutes」表記。0 の単位は出さない。"""
    total = int(seconds)
    parts = []
    for count, unit in ((total // 86400, "day"), (total % 86400 // 3600, "hour"), (total % 3600 // 60, "minute")):
        if count:
            parts.append(f"{count} {unit}{'s' if count != 1 else ''}")
    return ", ".join(parts) or "less than a minute"


@lru_cache(maxsize=1)
def static_facts() -> dict[str, str]:
    """再起動するまで変わらない項目。毎回読み直さない。"""
    facts = {"kernel": platform.release(), "hname": system_socket.gethostname(), "shell": "?", "user": "?", "distro": "?"}
    try:
        entry = pwd.getpwuid(os.getuid())
        facts["user"] = entry.pw_name
        # $SHELL は起動元（Claude Code なら zsh）を指すので passwd のログインシェルを見る
        facts["shell"] = Path(entry.pw_shell).name
    except (KeyError, OSError):
        pass
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                facts["distro"] = line.split("=", 1)[1].strip().strip('"')
                break
    except OSError:
        pass
    return facts


def read_packages() -> int:
    """fastfetch の packages {all} と同じ数。

    pacman だけだと合わない。fastfetch は ~/Applications の AppImage も数えるので、
    実機では pacman 1490 + appimage 2 = 1492 になる（`fastfetch --structure packages`
    で確認）。pacman の数は `pacman -Q | wc -l` と一致する。
    """
    total = 0
    try:
        total += sum(1 for entry in Path("/var/lib/pacman/local").iterdir() if entry.is_dir())
    except OSError:
        pass
    try:
        total += sum(1 for entry in (Path.home() / "Applications").iterdir()
                     if entry.is_file() and entry.suffix.lower() == ".appimage")
    except OSError:
        pass
    return total


# 3段目に出す「生きているもの」。名前は /proc/<pid>/comm と cmdline の両方で見る
# （electron 系は comm が "obsidian" にならないことがあるため）。
# ここに嘘を混ぜない。検出できないものは足さないこと。
WATCHED = (
    ("obsidian", ("obsidian",)),
    ("codex", ("codex",)),
    ("claude", ("claude",)),
    ("chrome", ("chrome", "chromium")),
    ("term", ("foot", "kitty", "alacritty")),
)


def read_processes(seen: dict[str, tuple[int, float]]) -> dict[str, dict[str, object]]:
    """監視対象ごとに、動いているか（alive）と処理中か（busy）を返す。

    busy は CPU 時間の増え方で見る。前回の観測との差分が要るので、
    最初の1回は必ず False になる（起動直後に「処理中」と嘘をつかないため）。

    `seen` は呼び出し側が持つ。モジュール変数にすると別インスタンスへ状態が
    漏れて「初回は False」が保証できなくなる（テストで実際に破れた）。
    """
    ticks = os.sysconf("SC_CLK_TCK")
    now = monotonic_ns() / 1e9
    totals = {name: 0 for name, _ in WATCHED}
    found = {name: False for name, _ in WATCHED}

    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip().lower()
            cmdline = (entry / "cmdline").read_bytes().decode("utf-8", "ignore").replace("\0", " ").lower()
            stat = (entry / "stat").read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        haystack = f"{comm} {cmdline}"
        for name, needles in WATCHED:
            if not any(n in haystack for n in needles):
                continue
            found[name] = True
            # stat は comm に空白を含みうるので、必ず最後の ')' より後ろを読む
            fields = stat[stat.rfind(")") + 2:].split()
            with suppress(IndexError, ValueError):
                totals[name] += int(fields[11]) + int(fields[12])  # utime + stime

    result: dict[str, dict[str, object]] = {}
    for name, _ in WATCHED:
        busy = False
        previous = seen.get(name)
        if previous is not None:
            elapsed = now - previous[1]
            if elapsed > 0:
                # 1コアの5%以上を使っていたら「処理中」とみなす
                busy = (totals[name] - previous[0]) / ticks / elapsed > 0.05
        seen[name] = (totals[name], now)
        result[name] = {"alive": found[name], "busy": busy and found[name]}
    return result


def read_vault(vault: Path) -> dict[str, object]:
    """Vault が git 管理下にあるか、未コミットが何件あるか。数えられなければ触れない。"""
    head = vault / ".git"
    if not head.exists():
        return {"tracked": False, "dirty": 0}
    dirty = 0
    try:
        # git を呼ばずに済ませたいが、状態の正確さは git にしか出せない
        out = subprocess.run(["git", "-C", str(vault), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=5)
        dirty = len([line for line in out.stdout.splitlines() if line.strip()])
    except (OSError, subprocess.SubprocessError):
        return {"tracked": True, "dirty": -1}  # 数えられなかった。0 と偽らない
    return {"tracked": True, "dirty": dirty}


def wallpaper_source() -> Path | None:
    """caelestia が今出している壁紙の実体パス。読めなければ None。"""
    try:
        raw = DEFAULT_WALLPAPER_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    source = Path(raw)
    return source if source.is_file() else None


def wallpaper_version(source: Path | None) -> str:
    """壁紙が変わったことを一意に表す札。パスと更新時刻から作る。"""
    if source is None:
        return ""
    try:
        stamp = source.stat().st_mtime_ns
    except OSError:
        return ""
    import hashlib
    return hashlib.sha256(f"{source}:{stamp}".encode()).hexdigest()[:16]


def wallpaper_webp(source: Path | None, version: str) -> Path | None:
    """壁紙を iPhone 向けの WebP に落として返す。同じ版があれば作り直さない。

    元は数MBになることがある。PNG のまま置いて初回表示が固まった事故があるので
    （2026-08-29、2枚で 6.3MB）、必ず縮めてから配る。
    """
    if source is None or not version:
        return None
    WALLPAPER_CACHE.mkdir(parents=True, exist_ok=True)
    out = WALLPAPER_CACHE / f"wallpaper-{version}.webp"
    if out.is_file():
        return out
    try:
        subprocess.run(
            ["magick", str(source), "-auto-orient",
             "-resize", f"{WALLPAPER_MAX}x{WALLPAPER_MAX}>",
             "-quality", str(WALLPAPER_QUALITY), str(out)],
            check=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # 古い版を片付ける（壁紙を変えるたびに溜まるため）
    for stale in WALLPAPER_CACHE.glob("wallpaper-*.webp"):
        if stale != out:
            with suppress(OSError):
                stale.unlink()
    return out if out.is_file() else None


def read_telemetry() -> dict[str, object]:
    used_ratio, used_gib, total_gib, uptime_seconds = 0.0, 0.0, 0.0, 0.0
    try:
        memory = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0])
        # fastfetch と同じ「total - available」を使用量とする（used+buff/cache ではない）
        total_kib, available_kib = memory["MemTotal"], memory["MemAvailable"]
        used_ratio = 100 * (1 - available_kib / total_kib)
        used_gib, total_gib = (total_kib - available_kib) / 1048576, total_kib / 1048576
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        pass
    return {
        "type": "system.telemetry",
        "load": round(os.getloadavg()[0], 2),
        "memory": round(used_ratio, 1),
        "uptime": format_uptime(uptime_seconds),
        "mem": f"{used_gib:.2f} GiB / {total_gib:.2f} GiB",
        "pkgs": read_packages(),
        **static_facts(),
        "host": system_socket.gethostname(),
        "ts": timestamp_ms(),
    }


def create_app(settings: Settings | None = None, scheme_path: Path = DEFAULT_SCHEME_PATH,
               vault_path: Path = DEFAULT_VAULT_PATH) -> FastAPI:
    config = settings or Settings.from_env()
    clients: set[WebSocket] = set()
    # busy 判定に使う直前の CPU 時間。アプリ単位で持つ（モジュール変数にしない）
    cpu_seen: dict[str, tuple[int, float]] = {}
    # 書き起こしはモデルを常駐させるのでアプリに1つだけ持つ（§8）
    transcriber = Transcriber()

    async def watch_scheme() -> None:
        previous = read_scheme(scheme_path)
        previous_paper = wallpaper_version(wallpaper_source())
        while True:
            scheme = read_scheme(scheme_path)
            if scheme != previous:
                previous = scheme
                event = scheme_event(scheme_path)
                for client in tuple(clients):
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await client.send_json(event)

            # 壁紙は配色と同じタイミングで変わる。版が変われば作り直して知らせる
            paper = wallpaper_version(wallpaper_source())
            if paper != previous_paper:
                previous_paper = paper
                event = wallpaper_event()
                for client in tuple(clients):
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await client.send_json(event)
            await asyncio.sleep(1)

    def wallpaper_event() -> dict[str, object]:
        source = wallpaper_source()
        version = wallpaper_version(source)
        # 変換に失敗したら version を空で返す。壁紙なしとして扱わせる
        ready = wallpaper_webp(source, version) is not None
        return {"type": "wallpaper.changed", "version": version if ready else "", "ts": timestamp_ms()}

    def live_event() -> dict[str, object]:
        """3段目に出す「今どうなっているか」。すべて実測。数えられないものは出さない。

        重い処理（/proc の全走査と git status）が入るので、5秒間隔の
        テレメトリと同じ便に乗せて回数を増やさない。
        """
        return {
            "type": "system.live",
            "apps": read_processes(cpu_seen),
            "vault": read_vault(vault_path),
            "phones": len(clients),   # 実際に繋がっている台数。サーバーが持っている
            "ts": timestamp_ms(),
        }

    async def push_telemetry() -> None:
        while True:
            events = (read_telemetry(), live_event())
            for client in tuple(clients):
                for event in events:
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await client.send_json(event)
            await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = config
        watcher = asyncio.create_task(watch_scheme())
        telemetry = asyncio.create_task(push_telemetry())
        try:
            yield
        finally:
            watcher.cancel()
            telemetry.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            with suppress(asyncio.CancelledError):
                await telemetry

    app = FastAPI(title="JARVIS Secretary", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "phase": 1, "connection": {"https": True, "websocket": True}}

    @app.get("/wallpaper.webp")
    async def wallpaper() -> Response:
        source = wallpaper_source()
        out = wallpaper_webp(source, wallpaper_version(source))
        if out is None:
            return Response(status_code=404)
        # 版ごとに別URLで取りに来るので、長く持たせてよい
        return FileResponse(out, media_type="image/webp",
                            headers={"Cache-Control": "public, max-age=604800, immutable"})

    @app.websocket("/ws")
    async def websocket_endpoint(socket: WebSocket) -> None:
        origin = socket.headers.get("origin")
        if config.allowed_origins and origin not in config.allowed_origins:
            await socket.close(code=1008, reason="origin not allowed")
            return
        await socket.accept()
        clients.add(socket)
        await socket.send_json({"type": "connection.ready", "ts": timestamp_ms()})
        await socket.send_json(scheme_event(scheme_path))
        await socket.send_json(wallpaper_event())
        await socket.send_json(read_telemetry())
        await socket.send_json(live_event())
        # §12「binary フレーム = 16kHz mono Int16 PCM」「text フレーム = JSON」
        splitter = SpeechSplitter()

        async def finish(utterance) -> None:
            """確定した発話を書き起こして返す。失敗は黙って捨てず理由を送る。"""
            logger.info("[STT] utterance %dms (%s)", utterance.ms, utterance.reason)
            result = await transcriber.transcribe(utterance.pcm)
            if result is None:
                await socket.send_json({
                    "type": "system.error", "code": "STT_UNAVAILABLE",
                    "message": transcriber.error or "model not loaded",
                    "retryable": False, "ts": timestamp_ms(),
                })
                return
            logger.info("[STT] %dms → %r", result.ms, result.text[:60])
            if not result.text:
                # §17「聞き取れませんでした」と返して LISTENING へ戻す
                await socket.send_json({
                    "type": "system.error", "code": "STT_FAILED",
                    "message": "聞き取れませんでした", "retryable": True, "ts": timestamp_ms(),
                })
                return
            await socket.send_json({
                "type": "audio.final", "text": result.text,
                "ms": utterance.ms, "took": result.ms, "ts": timestamp_ms(),
            })

        try:
            while True:
                packet = await socket.receive()
                if packet.get("type") == "websocket.disconnect":
                    break

                # 音声チャンク（20ms ごと）。VAD が発話の切れ目を決める
                chunk = packet.get("bytes")
                if chunk:
                    for utterance in splitter.feed(chunk):
                        await finish(utterance)
                    continue

                text = packet.get("text")
                if not text:
                    continue
                with suppress(json.JSONDecodeError):
                    message = json.loads(text)
                    if message.get("type") == "connection.ping":
                        await socket.send_json({"type": "connection.pong", "ts": timestamp_ms()})
                    elif message.get("type") == "clap.candidate":
                        logger.info(
                            "[WAKE] rms=%.3f hf=%.2f rise=%dms accepted=%s reason=%s",
                            float(message.get("rms", 0)),
                            float(message.get("hfRatio", 0)),
                            int(message.get("riseMs", 0)),
                            bool(message.get("accepted", False)),
                            str(message.get("reason", "unknown")),
                        )
                    elif message.get("type") == "session.sleep":
                        # 待機へ戻ったら、言いかけを持ち越さない
                        splitter.reset()
        except WebSocketDisconnect:
            pass
        finally:
            # 切断時に話しかけていた分は書き起こさない（返す先がもう無い）
            splitter.flush()
            clients.discard(socket)

    return app


app = create_app()
