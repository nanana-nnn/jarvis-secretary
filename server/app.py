from contextlib import asynccontextmanager
import logging
from time import monotonic_ns

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings


logger = logging.getLogger("uvicorn.error")


def timestamp_ms() -> int:
    return monotonic_ns() // 1_000_000


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = config
        yield

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
        await socket.send_json({"type": "connection.ready", "ts": timestamp_ms()})
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
            return

    return app


app = create_app()
