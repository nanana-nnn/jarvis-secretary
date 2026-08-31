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
from time import monotonic_ns

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings


logger = logging.getLogger("uvicorn.error")
DEFAULT_SCHEME_PATH = Path.home() / ".local/state/caelestia/scheme.json"
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


def create_app(settings: Settings | None = None, scheme_path: Path = DEFAULT_SCHEME_PATH) -> FastAPI:
    config = settings or Settings.from_env()
    clients: set[WebSocket] = set()

    async def watch_scheme() -> None:
        previous = read_scheme(scheme_path)
        while True:
            scheme = read_scheme(scheme_path)
            if scheme != previous:
                previous = scheme
                event = scheme_event(scheme_path)
                for client in tuple(clients):
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await client.send_json(event)
            await asyncio.sleep(1)

    async def push_telemetry() -> None:
        while True:
            event = read_telemetry()
            for client in tuple(clients):
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
        await socket.send_json(read_telemetry())
        try:
            while True:
                message = await socket.receive_json()
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
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(socket)

    return app


app = create_app()
