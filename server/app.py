"""FastAPI アプリの組み立て（DESIGN.md §12）。

**ここには配線しか置かない。** 中身はそれぞれの担当へ置く。

| 何を | どこ |
|---|---|
| 端末との会話（WS の受信ループ・書き起こし・応答） | `session.py` |
| 繋がっている端末と、配り続けるイベント | `hub.py` |
| 承認待ちの提案・監査ログ・自動却下 | `approval.py` |
| PC の実測値（テレメトリ・プロセス） | `facts.py` |
| caelestia の配色 | `scheme.py` |
| 壁紙の一覧・切り替え・変換 | `wallpapers.py` |
| Vault の git の状態 | `gitstate.py` |
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Response, WebSocket
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from . import wallpapers
from .agent import CodexAgent
from .approval import ApprovalStore
from .config import Settings
from .hub import Hub
from .scheme import DEFAULT_SCHEME_PATH
from .session import Session
from .transcribe import Transcriber

# 既存の import 経路を保つための再輸出。テストと外部から
# `server.app.<name>` で参照されている（実体は各モジュール）。
from .clock import timestamp_ms  # noqa: F401
from .facts import format_uptime, read_processes, read_telemetry  # noqa: F401
from .gitstate import dirty_paths, read_vault  # noqa: F401
from .scheme import read_primary, read_scheme, scheme_event  # noqa: F401

logger = logging.getLogger("uvicorn.error")

# 判断・記録の正本（AI_RULES.md の Vault）。VAULT_PATH で差し替えられる
DEFAULT_VAULT_PATH = Path(os.getenv("VAULT_PATH") or Path.home() / "ドキュメント/Start Vault")

wallpaper_version = wallpapers.current_version


def create_app(settings: Settings | None = None, scheme_path: Path = DEFAULT_SCHEME_PATH,
               vault_path: Path = DEFAULT_VAULT_PATH) -> FastAPI:
    config = settings or Settings.from_env()
    hub = Hub(vault_path, scheme_path)
    # 書き起こしはモデルを常駐させるのでアプリに1つだけ持つ（§8）
    transcriber = Transcriber()
    # エージェントは同時1ジョブ（§10）。アプリで1つ持って直列化する
    agent = CodexAgent(vault_path)
    approvals = ApprovalStore(vault_path, config.log_path)
    # どのバックエンドで動いているかは起動ログでしか分からない（.env は
    # 実行時に load_dotenv で読むので /proc/<pid>/environ には出ない）
    logger.info("[AGENT] %s", agent.command)
    logger.info("[AGENT] sandbox read=%s write=%s", agent.sandbox_read, agent.sandbox_write)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = config
        # 承認待ちの一覧。承認は WS ではなく HTTP で来るので、外から見える所に置く
        app.state.pending = approvals.pending
        tasks = (asyncio.create_task(hub.watch_scheme()),
                 asyncio.create_task(hub.push_telemetry()))
        # **先読みブリーフィングは動かさない**（2026-09-04、2026-09-05 に削除）。
        # 「今日のタスク」を Codex へ通す方針にしたので、先読みキャッシュを
        # 読む相手がいなくなった。動かしたままだと Vault のファイルが変わるたび
        # （デイリーへの1行追記でも）Codex が丸ごと1回走り、使われない答えを
        # 作り続ける＝トークンをそれだけ捨てることになる。
        # 直答へ戻すときは git 履歴から server/briefing.py と tests/test_briefing.py を
        # 復帰させる（最後に入っていたのは f883f54）
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="JARVIS Secretary", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.post("/jobs/{job_id}/approve")
    async def approve(job_id: str) -> dict[str, object]:
        return await approvals.resolve(job_id, approve=True)

    @app.post("/jobs/{job_id}/reject")
    async def reject(job_id: str) -> dict[str, object]:
        return await approvals.resolve(job_id, approve=False)

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "phase": 1, "connection": {"https": True, "websocket": True}}

    @app.get("/wallpaper.webp")
    async def wallpaper() -> Response:
        source = wallpapers.current_source()
        out = wallpapers.current_webp(source, wallpapers.current_version(source))
        if out is None:
            return Response(status_code=404)
        # 版ごとに別URLで取りに来るので、長く持たせてよい
        return FileResponse(out, media_type="image/webp",
                            headers={"Cache-Control": "public, max-age=604800, immutable"})

    @app.get("/wallpapers/{identifier}/thumb.webp")
    async def wallpaper_thumb(identifier: str) -> Response:
        """スライダーに並べるサムネイル。

        **一覧に載っているものしか返さない。** identifier はパスではなく札なので、
        任意のパスを送りつけても選択肢の外は取り出せない（wallpapers.resolve）
        """
        path = wallpapers.resolve(identifier)
        if path is None:
            return Response(status_code=404)
        out = await asyncio.to_thread(wallpapers.thumbnail, path, wallpapers.CACHE / "thumbs")
        if out is None:
            return Response(status_code=404)
        return FileResponse(out, media_type="image/webp",
                            headers={"Cache-Control": "public, max-age=604800, immutable"})

    @app.websocket("/ws")
    async def websocket_endpoint(socket: WebSocket) -> None:
        origin = socket.headers.get("origin")
        if config.allowed_origins and origin not in config.allowed_origins:
            await socket.close(code=1008, reason="origin not allowed")
            return
        await socket.accept()
        # 常設端末は1画面だけを音声入力元にする。古いPWAタブが残ると、
        # 同じ手拍子に複数インスタンスが反応して起動声や録音が重なる
        await hub.adopt(socket)
        session = Session(socket, hub, agent, transcriber, approvals)
        await session.greet()
        try:
            await session.run()
        finally:
            hub.release(socket)

    return app


app = create_app()
