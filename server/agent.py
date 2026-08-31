"""エージェントアダプター（DESIGN.md §10）。

MVP で実装するのは Codex のみ。Claude Code は同じ形で足せるようにしておく。

**コマンドはハードコードしない。** §10 のとおり `.env` の `CODEX_CMD` に
テンプレートで持ち、`{prompt_file}` `{cwd}` `{schema_file}` `{out_file}` を置換する。
`codex exec --help` で確認した確定形を `.env.example` に書いてある。

安全側の決めごと（§10「実行設定」）:
  - 作業ディレクトリは Vault 実パスに固定する
  - `read_only` では Codex 自体を `--sandbox read-only` で起動する
  - 削除・移動・改名はプロンプトで禁じ、read_only ではサンドボックスでも塞ぐ
  - 発話は引数に展開せず、**一時ファイル経由**で渡す（§10）
  - 同時実行は1ジョブ。新しい依頼は待たせる
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import shlex
import tempfile

logger = logging.getLogger("uvicorn.error")

# `codex exec --help`（2026-08-31 確認）で確定した形。
# --sandbox read-only  … モデルが動かすシェルを読み取りだけに縛る
# --cd                 … 作業ディレクトリを Vault に固定
# --output-schema      … 返す JSON の形を決める（末尾を自前で解析しなくて済む）
# --output-last-message… 最終メッセージをファイルへ書かせる
# --skip-git-repo-check… Vault が git 管理下でなくても動くように
DEFAULT_CODEX_CMD = (
    "codex exec --sandbox {sandbox} --cd {cwd} "
    "--output-schema {schema_file} --output-last-message {out_file} "
    "--skip-git-repo-check"
)
DEFAULT_TIMEOUT = 120          # §10「通常 120 秒」

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "spoken_reply", "sources"],
    "properties": {
        "summary": {"type": "string", "description": "画面用の要約。日本語。"},
        "spoken_reply": {"type": "string", "description": "読み上げ用。日本語80文字程度まで。"},
        "sources": {"type": "array", "items": {"type": "string"},
                    "description": "根拠にしたVault内のファイルパス"},
    },
}


@dataclass
class AgentResult:
    summary: str
    spoken_reply: str
    sources: list[str] = field(default_factory=list)
    error: str | None = None


def build_prompt(text: str, mode: str) -> str:
    """§10「プロンプト組み立て」の5点を必ず入れる。"""
    rule = ("**このセッションは読み取り専用です。ファイルを一切変更しないでください。**"
            if mode == "read_only" else
            "変更は提案にとどめ、勝手に確定しないでください。")
    return f"""あなたはこの Obsidian Vault を根拠に答える秘書です。

まず `_kit/AI_RULES.md` を読み、その規則に従ってください。
次に `00_home/home.md`（索引）を読み、必要なノートだけを開いてください。

{rule}
削除・移動・改名は禁止です。

利用者の発話: 「{text}」

出典が言えないことは書かないでください。分からなければ分からないと答えてください。
読み上げ用の返事は80文字程度までにしてください。
"""


class CodexAgent:
    """Codex CLI を非対話で回す。同時実行は1つに絞る（§10）。"""

    def __init__(self, vault: Path, command: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.vault = vault
        self.command = command or os.getenv("CODEX_CMD") or DEFAULT_CODEX_CMD
        self.timeout = timeout
        self._lock = asyncio.Lock()

    async def run(self, text: str, mode: str = "read_only") -> AgentResult:
        async with self._lock:                      # §10「同時実行は1ジョブ」
            return await self._run(text, mode)

    async def _run(self, text: str, mode: str) -> AgentResult:
        work = Path(tempfile.mkdtemp(prefix="jarvis-agent-"))
        prompt_file = work / "prompt.txt"
        schema_file = work / "schema.json"
        out_file = work / "answer.json"
        # 発話は引数に展開しない（§10）。ファイル経由で渡す
        prompt_file.write_text(build_prompt(text, mode), encoding="utf-8")
        schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")

        command = self.command.format(
            sandbox="read-only" if mode == "read_only" else "workspace-write",
            cwd=shlex.quote(str(self.vault)),
            prompt_file=shlex.quote(str(prompt_file)),
            schema_file=shlex.quote(str(schema_file)),
            out_file=shlex.quote(str(out_file)),
        )
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=prompt_file.open("rb"),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                # §17 AGENT_TIMEOUT「ジョブを中止し、変更を破棄して報告」
                return AgentResult("", "", error=f"AGENT_TIMEOUT ({self.timeout}s)")

            if process.returncode != 0:
                tail = (stderr or b"").decode("utf-8", "ignore").strip().splitlines()[-3:]
                return AgentResult("", "", error="AGENT_FAILED: " + " / ".join(tail))

            return self._parse(out_file)
        except OSError as exc:
            return AgentResult("", "", error=f"AGENT_FAILED: {exc}")
        finally:
            for path in (prompt_file, schema_file, out_file):
                try: path.unlink()
                except OSError: pass
            try: work.rmdir()
            except OSError: pass

    @staticmethod
    def _parse(out_file: Path) -> AgentResult:
        """返ってきた JSON を読む。読めなければ黙って空を返さず、理由を残す。"""
        try:
            payload = json.loads(out_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return AgentResult("", "", error=f"AGENT_FAILED: unreadable answer ({exc})")
        summary = str(payload.get("summary", "")).strip()
        spoken = str(payload.get("spoken_reply", "")).strip()
        sources = [str(s) for s in payload.get("sources", []) if isinstance(s, str)]
        if not spoken and not summary:
            return AgentResult("", "", error="AGENT_FAILED: empty answer")
        return AgentResult(summary=summary or spoken, spoken_reply=spoken or summary, sources=sources)
