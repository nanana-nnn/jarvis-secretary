import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
from pathlib import Path
import re
from time import monotonic_ns

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings


logger = logging.getLogger("uvicorn.error")
DEFAULT_SCHEME_PATH = Path.home() / ".local/state/caelestia/scheme.json"
HEX_COLOUR = re.compile(r"^[0-9a-fA-F]{6}$")


def timestamp_ms() -> int:
    return monotonic_ns() // 1_000_000


def read_primary(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["colours"]["primary"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return f"#{value.lower()}" if isinstance(value, str) and HEX_COLOUR.fullmatch(value) else None


def create_app(settings: Settings | None = None, scheme_path: Path = DEFAULT_SCHEME_PATH) -> FastAPI:
    config = settings or Settings.from_env()
    clients: set[WebSocket] = set()

    async def watch_scheme() -> None:
        previous = read_primary(scheme_path) or "#ffffff"
        while True:
            primary = read_primary(scheme_path) or "#ffffff"
            if primary != previous:
                previous = primary
                event = {"type": "scheme.changed", "primary": primary, "ts": timestamp_ms()}
                for client in tuple(clients):
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await client.send_json(event)
            await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = config
        watcher = asyncio.create_task(watch_scheme())
        try:
            yield
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher

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
        primary = read_primary(scheme_path) or "#ffffff"
        await socket.send_json({"type": "scheme.changed", "primary": primary, "ts": timestamp_ms()})
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
