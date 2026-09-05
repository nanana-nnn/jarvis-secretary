"""1台の端末との会話（DESIGN.md §6 / §9 / §12）。

受信ループは待たない。書き起こしとエージェントは 20〜40 秒かかるので、
そのあいだ `socket.receive()` が呼ばれないと音声フレームが溜まって接続が切れ、
端末が再接続して STANDBY へ戻る（2026-09-01 実機）。重い処理は必ず
`asyncio.create_task` に出し、ここは受け続けることだけをする。
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from . import note_writer
from . import vault as vault_reader
from . import wallpapers
from .agent import CodexAgent, LONG_TIMEOUT
from .approval import ApprovalStore
from .audio import NOISE_UTTERANCE_MS, SpeechSplitter
from .clock import timestamp_ms
from .gitstate import dirty_paths
from .hub import Hub
from .router import route
from .transcribe import Transcriber

logger = logging.getLogger("uvicorn.error")

# 長い仕事の経過を送る間隔。黙って待たせないための最低条件（2026-09-02）
PROGRESS_EVERY_S = 10


class Session:
    def __init__(self, socket: WebSocket, hub: Hub, agent: CodexAgent,
                 transcriber: Transcriber, approvals: ApprovalStore) -> None:
        self.socket = socket
        self.hub = hub
        self.agent = agent
        self.transcriber = transcriber
        self.approvals = approvals
        self.vault_path = hub.vault_path
        # §12「binary フレーム = 16kHz mono Int16 PCM」「text フレーム = JSON」
        self.splitter = SpeechSplitter()
        self.was_speaking = False
        # 走っている書き起こし・応答。受信ループの外で動かす
        self.job: asyncio.Task | None = None
        # 走っているエージェント。「やめて」で止めるためにここへ出しておく
        self.agent_task: asyncio.Task | None = None

    # --- 送信 -------------------------------------------------------------

    async def emit(self, payload: dict) -> bool:
        """切れたソケットへの送信で例外を上げない。

        エージェントは20〜40秒かかるので、返ってきた時点で端末が
        再接続済み＝この socket が閉じていることがある。そこで
        RuntimeError が出るとハンドラごと落ち、提案が捨てられる
        （2026-09-01 実機）。送れたかどうかだけ返す。
        """
        try:
            await self.socket.send_json(payload)
            return True
        except (RuntimeError, WebSocketDisconnect):
            return False

    async def greet(self) -> None:
        """繋がった直後に、今の状態を一式送る。"""
        await self.emit({"type": "connection.ready", "ts": timestamp_ms()})
        await self.emit(self.hub.scheme_event())
        await self.emit(self.hub.wallpaper_event())
        await self.emit(self.hub.telemetry_event())
        await self.emit(self.hub.live_event())

    # --- 受信ループ -------------------------------------------------------

    async def run(self) -> None:
        try:
            while True:
                packet = await self.socket.receive()
                if packet.get("type") == "websocket.disconnect":
                    break

                # 音声チャンク（20ms ごと）。VAD が発話の切れ目を決める
                chunk = packet.get("bytes")
                if chunk:
                    await self._on_audio(chunk)
                    continue

                text = packet.get("text")
                if not text:
                    continue
                with suppress(json.JSONDecodeError):
                    await self._on_message(json.loads(text))
        except WebSocketDisconnect:
            pass
        finally:
            # 切断時に話しかけていた分は書き起こさない（返す先がもう無い）
            self.splitter.flush()
            if self.job is not None and not self.job.done():
                self.job.cancel()
            if self.job is not None:
                with suppress(asyncio.CancelledError):
                    await self.job

    async def _on_audio(self, chunk: bytes) -> None:
        for utterance in self.splitter.feed(chunk):
            if self.job is not None and not self.job.done():
                # §10「同時実行は1ジョブ」。考えている最中のマイクは
                # ほぼ環境音なので、待たせずに捨てる。
                # **ただし「やめて」だけは通す。** 長い仕事ほど途中で
                # 止めたくなるので、割り込みの口をここに開ける
                # （2026-09-02。持ち時間を延ばした条件のひとつ）
                if self.agent_task is not None and not self.agent_task.done():
                    heard = await self.transcriber.transcribe(utterance.pcm)
                    if heard is not None and heard.text and route(heard.text).intent == "SYSTEM":
                        logger.info("[AGENT] stop requested: %r", heard.text[:40])
                        self.agent_task.cancel()
                        continue
                logger.info("[STT] busy, dropped utterance %dms", utterance.ms)
                continue
            self.job = asyncio.create_task(self.finish(utterance))
        # 話し始めたことを伝える。iPhone 側はこれで待機へ戻る
        # タイマーを止める（話している最中に寝てしまっていた）
        if self.splitter.speaking != self.was_speaking:
            self.was_speaking = self.splitter.speaking
            if self.was_speaking:
                await self.emit({"type": "audio.speaking", "ts": timestamp_ms()})

    async def _on_message(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "connection.ping":
            await self.emit({"type": "connection.pong", "ts": timestamp_ms()})
        elif kind == "clap.candidate":
            logger.info(
                "[WAKE] rms=%.3f hf=%.2f rise=%dms accepted=%s reason=%s",
                float(message.get("rms", 0)),
                float(message.get("hfRatio", 0)),
                int(message.get("riseMs", 0)),
                bool(message.get("accepted", False)),
                str(message.get("reason", "unknown")),
            )
            # 起きたら、作業を見せるターミナルを用意しておく。
            # 間違って閉じられていたらここで開き直す（本人の指定・
            # 2026-09-04）。話し終える頃には開いているので、
            # 依頼が来てから開くより間に合う
            if message.get("accepted") and self.agent.terminal is not None:
                await self.agent.terminal.ensure_running()
        elif kind == "text.input":
            # 拍手など、端末が確定させた固定入力をPC側のCodexへ渡す
            value = message.get("text")
            if isinstance(value, str) and value.strip() and (self.job is None or self.job.done()):
                self.job = asyncio.create_task(self.respond(value.strip()))
        elif kind == "wallpaper.select":
            # スライダーで選ばれた。**実際に PC の壁紙を変える。**
            # 配色の作り直しは caelestia がやり、Hub.watch_scheme が
            # scheme.changed / wallpaper.changed を配るので、
            # 画面の色と背景はそれで勝手に追従する
            chosen = message.get("id")
            path = wallpapers.resolve(chosen) if isinstance(chosen, str) else None
            ok = await wallpapers.apply(path) if path is not None else False
            await self.emit({
                "type": "wallpaper.applied", "ok": ok,
                "name": path.stem if path is not None else "",
                "ts": timestamp_ms(),
            })
        elif kind == "mic.health":
            # 実機のマイクが止まったときだけ届く。原因の切り分けに使う
            logger.warning(
                "[MIC] stalled context=%s track=%s muted=%s revived=%s",
                message.get("context"), message.get("track"),
                message.get("muted"), message.get("revived"),
            )
        elif kind in ("speech.started", "speech.ended", "speech.error"):
            logger.info("[TTS] %s detail=%s", kind, message.get("detail", ""))
        elif kind == "session.sleep":
            # 待機へ戻ったら、言いかけを持ち越さない
            self.splitter.reset()

    # --- 書き起こしと応答 -------------------------------------------------

    async def finish(self, utterance) -> None:
        """確定した発話を書き起こして返す。失敗は黙って捨てず理由を送る。"""
        logger.info("[STT] utterance %dms (%s)", utterance.ms, utterance.reason)
        result = await self.transcriber.transcribe(utterance.pcm)
        if result is None:
            await self.emit({
                "type": "system.error", "code": "STT_UNAVAILABLE",
                "message": self.transcriber.error or "model not loaded",
                "retryable": False, "ts": timestamp_ms(),
            })
            return
        logger.info("[STT] %dms → %r", result.ms, result.text[:60])
        if not result.text:
            # 短くて中身が無いものは物音。**黙って聞き続ける。**
            # ここでエラーを出すと、拍手の残響のたびに「聞き取れませんでした」
            # →聞き取り直しになり、光の1周も撃ち直される（2026-09-04 実機）
            if utterance.ms <= NOISE_UTTERANCE_MS:
                logger.info("[STT] ignored noise (%dms)", utterance.ms)
                return
            # §17「聞き取れませんでした」と返して LISTENING へ戻す
            await self.emit({
                "type": "system.error", "code": "STT_FAILED",
                "message": "聞き取れませんでした", "retryable": True, "ts": timestamp_ms(),
            })
            return
        await self.emit({
            "type": "audio.final", "text": result.text,
            "ms": utterance.ms, "took": result.ms, "ts": timestamp_ms(),
        })
        await self.respond(result.text)

    async def respond(self, text: str) -> None:
        """用件を判定して答える（§9）。決まった問いは即答、それ以外は Codex。"""
        decision = route(text)
        logger.info("[ROUTE] %s/%s matched=%r direct=%s",
                    decision.intent, decision.mode, decision.matched, decision.direct)

        # §9「SYSTEM を最優先で判定する（エージェントを起動しない）」
        if decision.intent == "SYSTEM":
            await self.emit({"type": "session.sleep", "reason": "system", "ts": timestamp_ms()})
            return

        if decision.intent == "WALLPAPER":
            await self._offer_wallpapers(decision)
            return

        # note の下書き（2026-09-05）。Codex に書かせて、そのまま下書きまで運ぶ
        if decision.intent == "NOTE":
            await self._write_note(text, decision)
            return

        # 決まった問いはファイルを読むだけで返す。Codex は実測 42.6 秒かかる
        if decision.direct:
            found = vault_reader.answer(self.vault_path, decision.direct)
            if found is not None:
                await self._started(decision, long=False)
                await self.emit({
                    "type": "agent.completed", "intent": decision.intent,
                    "summary": found.summary, "spoken_reply": found.spoken_reply,
                    "sources": found.sources, "took": 0, "ts": timestamp_ms(),
                })
                return

        await self._run_agent(text, decision)

    async def _started(self, decision, long: bool) -> None:
        """UI は audio.final で TRANSCRIBING へ入り、agent.started を受けて
        初めて先へ進める（§6）。ここを飛ばすと TRANSCRIBING で止まる
        （2026-09-01 に実機で固まっている）。どの経路でも必ず通すこと。"""
        await self.emit({
            "type": "agent.started", "intent": decision.intent,
            "matched": decision.matched, "long": long, "ts": timestamp_ms(),
        })

    async def _offer_wallpapers(self, decision) -> None:
        """壁紙を選ぶ（2026-09-05）。1段目のカードをスライダーへ差し替えるだけで、
        Codex も Vault も通らない。選んだあとの反映は wallpaper.select 側。"""
        items = await asyncio.to_thread(wallpapers.find_all)
        await self._started(decision, long=False)
        await self.emit({
            "type": "wallpaper.choices",
            "items": [{"id": identifier, "name": path.stem} for identifier, path in items],
            "ts": timestamp_ms(),
        })

    async def _agent_with_progress(self, text: str, decision, mode: str, use_session: bool):
        """エージェントを回しながら経過を送る。返すのは (結果, かかった時間ms)。

        結果が None なら「もう端末へ伝え終えた」（「やめて」で中断／エラー送信済み）。
        **黙って待たせない。** 経過を送り続け、「やめて」で止められる状態を保つのが
        持ち時間を延ばす条件（2026-09-02。長い仕事ほど途中で止めたくなる）。
        """
        started = timestamp_ms()
        self.agent_task = asyncio.create_task(
            self.agent.run(text, mode, timeout=LONG_TIMEOUT if decision.long else None,
                           use_session=use_session))
        try:
            while True:
                done, _ = await asyncio.wait({self.agent_task}, timeout=PROGRESS_EVERY_S)
                if done:
                    break
                await self.emit({
                    "type": "agent.progress", "intent": decision.intent,
                    "elapsed": (timestamp_ms() - started) // 1000, "ts": timestamp_ms(),
                })
            outcome = self.agent_task.result()
        except asyncio.CancelledError:
            # 「やめて」で割り込まれた。提案は作られていないので捨てるものは無い
            logger.info("[AGENT] cancelled by user (%dms)", timestamp_ms() - started)
            # **走っているエージェントも必ず止める。** 「やめて」の経路では
            # 呼び出し側が既に cancel 済みだが、端末が切れてジョブごと畳まれた
            # ときはここが唯一の止め口で、放っておくと Codex が残る
            if self.agent_task is not None and not self.agent_task.done():
                self.agent_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self.agent_task
            await self.emit({"type": "agent.cancelled", "intent": decision.intent, "ts": timestamp_ms()})
            return None, 0
        finally:
            self.agent_task = None
        took = timestamp_ms() - started
        if outcome.error:
            logger.warning("[AGENT] %s (%dms)", outcome.error, took)
            await self.emit({
                "type": "system.error", "code": outcome.error.split(":")[0],
                "message": outcome.error, "retryable": True, "ts": timestamp_ms(),
            })
            return None, took
        return outcome, took

    async def _write_note(self, text: str, decision) -> None:
        """Codex に本文を書かせ、そのまま note の下書きまで運ぶ（2026-09-05）。

        **Vault は変えない**（読み取り専用で走らせる）。**公開に触れない。**
        失敗しても作り直さない ── 同じ編集URLを見てもらう（§18.1）。
        """
        await self._started(decision, long=True)
        if note_writer.busy():
            await self.emit({
                "type": "system.error", "code": "NOTE_BUSY",
                "message": "いま別の下書きを作ってる。終わってからもう一度言って",
                "retryable": True, "ts": timestamp_ms(),
            })
            return
        outcome, took = await self._agent_with_progress(text, decision, "note", use_session=False)
        if outcome is None:
            return
        # 本文はできた。ここから先はブラウザ操作なので、まだ待つことを伝える
        await self.emit({
            "type": "agent.progress", "intent": decision.intent,
            "elapsed": took // 1000, "ts": timestamp_ms(),
        })
        logger.info("[NOTE] writing draft: %r (%d字)", outcome.title[:40], len(outcome.body))
        # サムネは本人が発話で明示したときだけ作る。記事だけ頼まれた場合は
        # 本文の下書き保存までに留める。
        with_thumbnail = "サムネ" in text
        result = await note_writer.write(
            outcome.title, outcome.body, with_thumbnail=with_thumbnail,
        )
        if not result.get("ok"):
            await self.emit({
                "type": "system.error", "code": str(result.get("error", "note_failed")).upper(),
                "message": result.get("message") or "下書きにできなかった。noteの画面を見て",
                "retryable": False, "ts": timestamp_ms(),
            })
            return
        await self.emit({
            "type": "agent.completed", "intent": decision.intent,
            "summary": "下書きにしたよ。\n" + outcome.title + "\n" + str(result.get("url", "")),
            "spoken_reply": outcome.spoken_reply or "下書きにしたよ。",
            "sources": outcome.sources, "took": took, "ts": timestamp_ms(),
        })

    async def _run_agent(self, text: str, decision) -> None:
        # ここから先は時間がかかる。待たせると分かるよう先に知らせる（§12）
        await self._started(decision, long=decision.long)
        # §11-1 実行前の状態を保存する。実行後に取ると、ユーザーが作業中に
        # 触ったぶんと区別できなくなる
        before_dirty = dirty_paths(self.vault_path) if decision.mode == "propose_write" else None
        outcome, took = await self._agent_with_progress(text, decision, decision.mode, use_session=True)
        if outcome is None:
            return
        if outcome.proposed_root is not None:
            await self._offer_approval(text, decision, outcome, before_dirty)
            return
        logger.info("[AGENT] %dms → %r", took, outcome.spoken_reply[:60])
        await self.emit({
            "type": "agent.completed", "intent": decision.intent,
            "summary": outcome.summary, "spoken_reply": outcome.spoken_reply,
            "sources": outcome.sources, "took": took, "ts": timestamp_ms(),
        })

    async def _offer_approval(self, text: str, decision, outcome, before_dirty: set[str] | None) -> None:
        """The agent changed only its temporary Vault copy.  Keep that copy as the
        exact approval artifact; the real Vault remains untouched until the HTTP
        approval endpoint verifies and applies it."""
        job_id = uuid.uuid4().hex
        # §11-3 既にユーザーの未コミット変更があるファイルは、承認画面で警告を出す。
        # 止めはしない（判断はユーザー）が、黙って上書きさせない
        if before_dirty is None:
            warnings = ["未コミット変更を確認できませんでした。上書き前に手元で確認してください。"]
        else:
            warnings = [f"{name} には未コミットの変更があります。承認すると上書きされます。"
                        for name in outcome.changed_files if name in before_dirty]
        self.approvals.hold(job_id, {
            "proposal": outcome.proposed_root,
            "original_contents": outcome.original_contents,
            "changed_files": outcome.changed_files,
            "intent": decision.intent,
            "text": text,
            "summary": outcome.summary,
            "spoken_reply": outcome.spoken_reply,
            "warnings": warnings,
        }, self.socket)
        sent = await self.emit({
            "type": "approval.required", "job_id": job_id,
            "summary": outcome.summary, "changed_files": outcome.changed_files,
            "diff": outcome.diff, "warnings": warnings, "ts": timestamp_ms(),
        })
        if not sent:
            # 承認画面を出せなかった提案は残さない。押す手段が無いまま
            # Vault 1個ぶんのコピーが temp に積まれる
            logger.warning("[AGENT] approval could not be delivered; proposal dropped")
            self.approvals.drop(job_id, "undeliverable")
