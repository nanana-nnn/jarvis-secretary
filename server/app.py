import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket as system_socket
import tempfile
from time import monotonic_ns

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings


logger = logging.getLogger("uvicorn.error")
DEFAULT_SCHEME_PATH = Path.home() / ".local/state/caelestia/scheme.json"
HEX_COLOUR = re.compile(r"^[0-9a-fA-F]{6}$")

# ~/.config/caelestia/sysmon-dots.py と同じ cava 設定。BARS=20 を合わせておかないと
# iPhone側の極座標マッピング（PixelCore.tsx の BAR_COUNT）とずれる
CAVA_BARS = 20
CAVA_CONFIG = """[general]
framerate = 30
bars = {bars}
autosens = 1
[input]
method = pulse
source = auto
[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 100
channels = mono
[smoothing]
noise_reduction = 40
""".format(bars=CAVA_BARS)
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


def read_telemetry() -> dict[str, object]:
    try:
        memory = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0])
        used = 100 * (1 - memory["MemAvailable"] / memory["MemTotal"])
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, KeyError, ValueError):
        used, uptime_seconds = 0.0, 0.0
    days, remainder = divmod(int(uptime_seconds), 86400)
    hours = remainder // 3600
    return {"type": "system.telemetry", "load": round(os.getloadavg()[0], 2), "memory": round(used, 1), "uptime": f"{days}D {hours}H", "host": system_socket.gethostname(), "ts": timestamp_ms()}


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

    async def stream_audio_bands() -> None:
        # PCのシステム音声（cavaのpulse autoソース＝既定シンクのモニター）を20帯域化して
        # 常時配信する。本物の sysmon dots パネルと同じ音源にすることで「常に動いている」を
        # そのまま再現する。iPhoneのマイクには依存しない
        tmp_dir = Path(tempfile.mkdtemp(prefix="jarvis-cava-"))
        config_path = tmp_dir / "cava.conf"
        config_path.write_text(CAVA_CONFIG, encoding="utf-8")
        try:
            while True:
                process: asyncio.subprocess.Process | None = None
                try:
                    process = await asyncio.create_subprocess_exec(
                        "cava", "-p", str(config_path),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    )
                    assert process.stdout is not None
                    async for raw in process.stdout:
                        line = raw.decode("ascii", "ignore").strip().rstrip(";")
                        if not line:
                            continue
                        bands = [int(v) / 100 for v in line.split(";") if v]
                        if len(bands) != CAVA_BARS:
                            continue
                        event = {"type": "audio.bands", "bands": bands, "ts": timestamp_ms()}
                        for client in tuple(clients):
                            with suppress(RuntimeError, WebSocketDisconnect):
                                await client.send_json(event)
                except FileNotFoundError:
                    logger.warning("[AUDIO] cava is not installed; dots panel falls back to client-side motion")
                    return
                finally:
                    if process is not None and process.returncode is None:
                        process.terminate()
                        with suppress(ProcessLookupError):
                            await process.wait()
                # cava が落ちても（Bluetoothの出力先切替など）3秒後に立て直す
                await asyncio.sleep(3)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = config
        watcher = asyncio.create_task(watch_scheme())
        telemetry = asyncio.create_task(push_telemetry())
        audio = asyncio.create_task(stream_audio_bands())
        try:
            yield
        finally:
            watcher.cancel()
            telemetry.cancel()
            audio.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            with suppress(asyncio.CancelledError):
                await telemetry
            with suppress(asyncio.CancelledError):
                await audio

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
