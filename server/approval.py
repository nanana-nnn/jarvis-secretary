"""承認待ちの提案を預かる（DESIGN.md §11）。

**実 Vault は承認されるまで一切変わらない。** エージェントが書くのは temp の
コピーで、ここが預かるのはそのコピーへのパスと、実行前の中身の控え。
承認されたときだけ、控えと現物を突き合わせてから適用する。

承認は WS ではなく HTTP で来るので、預かり先は WS ハンドラの外に要る
（`app.state.pending` として公開している）。
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
from pathlib import Path
import shutil

from fastapi import HTTPException, WebSocket

from .clock import timestamp_ms
from .write import WriteRejected, apply_proposal

logger = logging.getLogger("uvicorn.error")

# §11 承認フロー「120秒無操作 → 自動却下」
APPROVAL_TIMEOUT_S = 120


class ApprovalStore:
    """提案の保管、監査ログ、自動却下タイマーをまとめて持つ。"""

    def __init__(self, vault_path: Path, log_path: str) -> None:
        self.vault_path = vault_path
        self.log_path = log_path
        self.pending: dict[str, dict[str, object]] = {}

    def log(self, entry: dict[str, object]) -> None:
        """Append-only audit log outside the Vault (DESIGN.md §11)."""
        path = Path(self.log_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": timestamp_ms(), **entry}, ensure_ascii=False) + "\n")

    def discard(self, job: dict[str, object]) -> None:
        """Drop the proposal copy. The real Vault was never touched, so there is nothing to undo."""
        timer = job.get("timer")
        if isinstance(timer, asyncio.Task) and timer is not asyncio.current_task():
            timer.cancel()
        proposal = job["proposal"]
        if isinstance(proposal, Path):
            shutil.rmtree(proposal.parent, ignore_errors=True)

    def hold(self, job_id: str, job: dict[str, object], socket: WebSocket) -> None:
        """提案を預かり、自動却下のタイマーを掛ける。"""
        self.pending[job_id] = job
        job["timer"] = asyncio.create_task(self._auto_reject(job_id, socket))

    def drop(self, job_id: str, reason: str) -> None:
        """承認画面を出せなかった提案を捨てる。押す手段が無いまま temp に積まれるのを防ぐ。"""
        stale = self.pending.pop(job_id, None)
        if stale is None:
            return
        self.log({"intent": stale["intent"], "text": stale["text"],
                  "changed_files": stale["changed_files"], "approved": False, "reason": reason})
        self.discard(stale)

    async def resolve(self, job_id: str, approve: bool) -> dict[str, object]:
        job = self.pending.pop(job_id, None)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown or expired job")
        proposal = job["proposal"]
        assert isinstance(proposal, Path)
        timer = job.get("timer")
        if isinstance(timer, asyncio.Task) and timer is not asyncio.current_task():
            timer.cancel()
        try:
            if not approve:
                self.log({"intent": job["intent"], "text": job["text"], "changed_files": job["changed_files"],
                          "approved": False, "reason": "rejected"})
                return {"job_id": job_id, "applied": False, "summary": "変更を破棄したよ。", "spoken_reply": "変更を破棄したよ。"}
            originals = job["original_contents"]
            assert isinstance(originals, dict)
            for relative, original in originals.items():
                target = self.vault_path / str(relative)
                current = target.read_bytes() if target.is_file() else None
                if current != original:
                    self.log({"intent": job["intent"], "text": job["text"], "changed_files": job["changed_files"],
                              "approved": False, "reason": "conflict", "conflict": str(relative)})
                    raise HTTPException(status_code=409, detail="VAULT_DIRTY: target changed after proposal")
            changed = job["changed_files"]
            assert isinstance(changed, list)
            apply_proposal(self.vault_path, proposal, [str(path) for path in changed])
            self.log({"intent": job["intent"], "text": job["text"], "changed_files": changed,
                      "approved": True, "warnings": job.get("warnings", [])})
            return {"job_id": job_id, "applied": True, "summary": job["summary"], "spoken_reply": job["spoken_reply"]}
        except WriteRejected as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            shutil.rmtree(proposal.parent, ignore_errors=True)

    async def _auto_reject(self, job_id: str, socket: WebSocket) -> None:
        """§11「120秒無操作 → 自動却下」。提案は破棄し、端末にも結果を返す。

        タイマーを置かないと、提案の Vault コピーが temp に残り続ける。
        承認画面を開いたまま端末が寝る／離れるのは常設端末では普通に起きる。
        """
        try:
            await asyncio.sleep(APPROVAL_TIMEOUT_S)
        except asyncio.CancelledError:
            return
        job = self.pending.pop(job_id, None)
        if job is None:
            return
        self.log({"intent": job["intent"], "text": job["text"], "changed_files": job["changed_files"],
                  "approved": False, "reason": "timeout"})
        self.discard(job)
        with suppress(Exception):
            await socket.send_json({
                "type": "agent.completed", "intent": job["intent"], "job_id": job_id, "applied": False,
                "summary": "確認がなかったから変更を破棄したよ。",
                "spoken_reply": "確認がなかったから変更を破棄したよ。",
                "sources": [], "took": 0, "ts": timestamp_ms(),
            })
