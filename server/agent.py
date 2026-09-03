"""エージェントアダプター（DESIGN.md §10）。

既定は Codex CLI（§2 の確定事項）。**バックエンドはコマンドテンプレートで決まる**ので、
Claude Code へは `.env` の差し替えだけで切り替わる（クラスは共通のまま）。

**コマンドはハードコードしない。** §10 のとおり `.env` の `AGENT_CMD`
（旧 `CODEX_CMD` も可）にテンプレートで持ち、`{sandbox}` `{prompt_file}` `{cwd}`
`{schema_file}` `{out_file}` を置換する。両方の確定形を `.env.example` に書いてある。

契約は3つだけ。ここさえ満たせばどの CLI でも入る:
  - プロンプトは **stdin** から受け取る
  - 答えの JSON（SCHEMA の形）を **{out_file} へ書く**
  - 終了コード 0 が成功

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
import shutil
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
    "--skip-git-repo-check -"
)

# 会話の続き（2026-09-03、本人の指定：手を叩く→codex→obsidian→なにする？の
# あと、返事が続けて同じ会話として続くようにする）。
# `codex exec resume --last` は --sandbox/--cd を取らない（resume はセッションを
# 作った時点の設定をそのまま使う。§10 の安全側の決めごとはブートストラップ側の
# コマンドで一度固定すれば以降も効いたまま）。propose_write は毎回ちがう
# 使い捨てコピーが作業ディレクトリになるので、resume の対象にしない
# （run() の use_session は mode=="read_only" のときだけ効く）
DEFAULT_RESUME_CMD = (
    "codex exec resume --last "
    "--output-schema {schema_file} --output-last-message {out_file} "
    "--skip-git-repo-check -"
)

# {sandbox} に入れる値。codex は --sandbox の引数だが、他の CLI では別の
# フラグになる（Claude Code なら --allowedTools / --permission-mode）。
# コード側に残っていた唯一の codex 固有部分なので .env から差し替えられるようにする。
# §2「アダプター層は差し替え可能に保つ」
DEFAULT_SANDBOX_READ = "read-only"
DEFAULT_SANDBOX_WRITE = "workspace-write"
DEFAULT_TIMEOUT = 120          # §10「通常 120 秒」
# 記事の執筆・調べ物は分単位かかる。120秒で殺すと「秘書として何もできない」に
# なるので、時間のかかる用件（router.LONG_TASK）だけこちらを使う。
# 待たせるぶん、進捗を送り、「やめて」で止められるようにするのが条件（2026-09-02）
LONG_TIMEOUT = int(os.getenv("AGENT_LONG_TIMEOUT", "900"))   # 15分

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
    changed_files: list[str] = field(default_factory=list)
    diff: str = ""
    proposed_root: Path | None = None
    original_contents: dict[str, bytes | None] = field(default_factory=dict)
    error: str | None = None


def build_prompt(text: str, mode: str) -> str:
    """§10「プロンプト組み立て」の5点を必ず入れる。"""
    # propose_write の作業ディレクトリは Vault そのものではなく使い捨てのコピー
    # （§11「エージェントには一時作業領域で変更させ、承認後に Vault へ適用する」）。
    # ここで「変更しないで」と言うと編集が起きず、差分が空になって承認画面が
    # 出ない。コピーを編集することが提案そのものだと明示する
    rule = ("**このセッションは読み取り専用です。ファイルを一切変更しないでください。**"
            if mode == "read_only" else
            "**この作業ディレクトリは Vault の使い捨てコピーです。"
            "必要な変更はここのファイルに実際に書いてください。**\n"
            "書いた内容は本人が差分を見て承認するまで本物の Vault には入りません。"
            "変更は依頼された1件だけにとどめ、ついでの整理をしないでください。")
    return f"""あなたはこの Obsidian Vault を根拠に答える秘書です。

まず `_kit/AI_RULES.md` を読み、その規則に従ってください。
次に `00_home/home.md`（索引）を読み、必要なノートだけを開いてください。

{rule}
削除・移動・改名は禁止です。

利用者の発話: 「{text}」

出典が言えないことは書かないでください。分からなければ分からないと答えてください。
読み上げ用の返事は80文字程度まで、必ず親しいタメ口で書いてください。敬語は使わないでください。

最終メッセージは次のJSONだけを返してください。前後に説明やコードフェンスを付けないでください。
{{"summary":"画面用の要約(日本語)","spoken_reply":"読み上げ用(日本語80文字程度)","sources":["根拠にしたVault内のファイルパス"]}}
"""


class CodexAgent:
    """Codex CLI を非対話で回す。同時実行は1つに絞る（§10）。"""

    def __init__(self, vault: Path, command: str | None = None, resume_command: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT) -> None:
        self.vault = vault
        # AGENT_CMD が新しい名前。CODEX_CMD は既存の .env をそのまま動かすため残す
        self.command = command or os.getenv("AGENT_CMD") or os.getenv("CODEX_CMD") or DEFAULT_CODEX_CMD
        self.resume_command = resume_command or os.getenv("AGENT_RESUME_CMD") or DEFAULT_RESUME_CMD
        self.sandbox_read = os.getenv("AGENT_SANDBOX_READ") or DEFAULT_SANDBOX_READ
        self.sandbox_write = os.getenv("AGENT_SANDBOX_WRITE") or DEFAULT_SANDBOX_WRITE
        self.timeout = timeout
        self._lock = asyncio.Lock()
        # このサーバー起動中に、会話用のセッションを一度でも作れたか。
        # まだなら resume を試さずブートストラップ側で作る（無いものを resume
        # すると失敗するため）。サーバーを再起動すると新しい会話として始まる
        self._session_started = False

    async def run(self, text: str, mode: str = "read_only", timeout: int | None = None,
                  use_session: bool = False) -> AgentResult:
        """timeout を渡すとこの1回だけ持ち時間を変える（記事執筆や調べ物は分単位かかる）。

        use_session=True で、直前の会話の続きとして投げる（2026-09-03）。
        read_only 以外（propose_write は毎回使い捨てコピーが作業ディレクトリに
        なる）では効かない。先読みブリーフィング（briefing.py）はここを
        False のままにして、本人の会話へ割り込ませない。
        """
        async with self._lock:                      # §10「同時実行は1ジョブ」
            return await self._run(text, mode, timeout or self.timeout, use_session and mode == "read_only")

    async def _run(self, text: str, mode: str, timeout: int, use_session: bool) -> AgentResult:
        work = Path(tempfile.mkdtemp(prefix="jarvis-agent-"))
        prompt_file = work / "prompt.txt"
        schema_file = work / "schema.json"
        out_file = work / "answer.json"
        # 発話は引数に展開しない（§10）。ファイル経由で渡す
        prompt_file.write_text(build_prompt(text, mode), encoding="utf-8")
        schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")

        # Phase 4: proposal runs must never receive the real Vault as a writable
        # directory.  Copy it before invoking Codex, then keep that copy until
        # the user has approved or rejected the resulting diff.
        proposed_root: Path | None = None
        cwd = self.vault
        if mode == "propose_write":
            proposed_root = work / "vault"
            try:
                shutil.copytree(self.vault, proposed_root, ignore=shutil.ignore_patterns(".git"))
            except OSError as exc:
                shutil.rmtree(work, ignore_errors=True)
                return AgentResult("", "", error=f"AGENT_FAILED: proposal copy ({exc})")
            cwd = proposed_root

        resuming = use_session and self._session_started
        template = self.resume_command if resuming else self.command
        command = template.format(
            sandbox=self.sandbox_read if mode == "read_only" else self.sandbox_write,
            cwd=shlex.quote(str(cwd)),
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
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                # §17 AGENT_TIMEOUT「ジョブを中止し、変更を破棄して報告」
                shutil.rmtree(work, ignore_errors=True)
                proposed_root = None
                return AgentResult("", "", error=f"AGENT_TIMEOUT ({timeout}s)")
            except asyncio.CancelledError:
                # 「やめて」で割り込まれた。子プロセスを残さず片付けてから伝える
                process.kill()
                await process.wait()
                shutil.rmtree(work, ignore_errors=True)
                proposed_root = None
                raise

            if process.returncode != 0:
                if resuming:
                    # resume 先のセッションが失われている（サーバー外で codex の
                    # 保存が消えた等）。次回はブートストラップからやり直す
                    self._session_started = False
                tail = (stderr or b"").decode("utf-8", "ignore").strip().splitlines()[-3:]
                shutil.rmtree(work, ignore_errors=True)
                proposed_root = None
                return AgentResult("", "", error="AGENT_FAILED: " + " / ".join(tail))

            outcome = self._parse(out_file)
            if proposed_root is not None:
                if outcome.error:
                    # 答えが読めないまま提案コピーを残すと、承認に出せないまま
                    # temp に Vault 1個ぶんが積まれ続ける
                    shutil.rmtree(work, ignore_errors=True)
                    return outcome
                outcome.proposed_root = proposed_root
                outcome.changed_files, outcome.diff = _changes(self.vault, proposed_root)
                outcome.original_contents = {
                    relative: (self.vault / relative).read_bytes() if (self.vault / relative).is_file() else None
                    for relative in outcome.changed_files
                }
                if not outcome.changed_files:
                    outcome.proposed_root = None
                    shutil.rmtree(work, ignore_errors=True)
            if use_session and not outcome.error:
                self._session_started = True
            return outcome
        except OSError as exc:
            shutil.rmtree(work, ignore_errors=True)
            proposed_root = None
            return AgentResult("", "", error=f"AGENT_FAILED: {exc}")
        finally:
            for path in (prompt_file, schema_file, out_file):
                try: path.unlink()
                except OSError: pass
            # A proposed Vault copy is retained for the approval endpoint.  All
            # other runs remove their complete temporary directory immediately.
            if proposed_root is None:
                shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _parse(out_file: Path) -> AgentResult:
        """返ってきた JSON を読む。読めなければ黙って空を返さず、理由を残す。"""
        try:
            raw = out_file.read_text(encoding="utf-8")
        except OSError as exc:
            return AgentResult("", "", error=f"AGENT_FAILED: unreadable answer ({exc})")
        payload = _json_object(raw)
        if payload is None:
            head = " ".join(raw.split())[:80]
            return AgentResult("", "", error=f"AGENT_FAILED: unreadable answer ({head!r})")
        summary = str(payload.get("summary", "")).strip()
        spoken = str(payload.get("spoken_reply", "")).strip()
        sources = [str(s) for s in payload.get("sources", []) if isinstance(s, str)]
        if not spoken and not summary:
            return AgentResult("", "", error="AGENT_FAILED: empty answer")
        return AgentResult(summary=summary or spoken, spoken_reply=spoken or summary, sources=sources)


def _json_object(raw: str) -> dict | None:
    """本文から答えの JSON を取り出す。

    「JSONだけ返して」と指示してもコードフェンスや一言が前後に付くことがある。
    形が合っているのに1文字の余分で提案ごと捨てるのは損なので、素で読めなければ
    最初の `{` から釣り合う `}` までを取り出して読み直す。
    `--output-schema` を持たない CLI（Claude Code）では特に起きやすい。
    """
    for candidate in (raw, _first_object(raw)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _first_object(raw: str) -> str | None:
    """最初の `{` から、括弧の釣り合う `}` までを返す。文字列内の括弧は数えない。"""
    start = raw.find("{")
    if start < 0:
        return None
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(raw)):
        char = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start:index + 1]
    return None


def _changes(original: Path, proposed: Path) -> tuple[list[str], str]:
    """Return an approval diff; deletions and paths outside the copy are rejected later."""
    import difflib

    paths = {
        path.relative_to(original).as_posix()
        for path in original.rglob("*") if path.is_file() and ".git" not in path.parts
    } | {
        path.relative_to(proposed).as_posix()
        for path in proposed.rglob("*") if path.is_file()
    }
    changed: list[str] = []
    chunks: list[str] = []
    for relative in sorted(paths):
        before, after = original / relative, proposed / relative
        old = before.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if before.is_file() else []
        new = after.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if after.is_file() else []
        if old == new:
            continue
        changed.append(relative)
        chunks.extend(difflib.unified_diff(old, new, fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    return changed, "".join(chunks)
