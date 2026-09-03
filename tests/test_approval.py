"""Phase 4 の合格条件（DESIGN.md §18）を機械で確かめる。

  「却下時はファイルが変化せず、承認時だけ指定先へ追記される。既存変更を壊さない。」

承認は WS ではなく HTTP で来るので、承認待ちは `app.state.pending` に置いてある。
ここではそこへ提案を1件入れ、エンドポイントの実物を叩いて Vault の中身を見る。
"""
from pathlib import Path
import asyncio
from functools import wraps
import json
import subprocess

from fastapi.testclient import TestClient

from server.app import create_app, dirty_paths
from server.config import Settings


def _sync(test):
    """非同期のテストを普通のテストとして回す（tests/test_briefing.py と同じ理由）。"""
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


NO_SCHEME = Path("/nonexistent/scheme.json")


def _settings(log: Path) -> Settings:
    """操作ログの行き先はテストごとの temp に向ける（§11-10 の追記先）。"""
    return Settings("127.0.0.1", 8787, Path("cert"), Path("key"), ("https://phone.test",), log_path=log)


def _vault_with_proposal(tmp_path: Path) -> tuple[Path, Path, Path]:
    """実 Vault と、エージェントが書き換えた「提案コピー」を作る。

    提案コピーは temp ディレクトリの中に置く（実装が承認後に親ごと消すため）。
    """
    vault = tmp_path / "vault"
    (vault / "01_daily").mkdir(parents=True)
    (vault / "01_daily" / "2026-09-01.md").write_text("## 取り込み\n", encoding="utf-8")
    (vault / "keep.md").write_text("触らない\n", encoding="utf-8")

    work = tmp_path / "work"
    proposal = work / "vault"
    (proposal / "01_daily").mkdir(parents=True)
    (proposal / "01_daily" / "2026-09-01.md").write_text("## 取り込み\n- 追記された1行\n", encoding="utf-8")
    (proposal / "keep.md").write_text("触らない\n", encoding="utf-8")
    return vault, proposal, work


def _pend(app, vault: Path, proposal: Path, changed: list[str]) -> str:
    originals = {
        name: (vault / name).read_bytes() if (vault / name).is_file() else None
        for name in changed
    }
    app.state.pending["job1"] = {
        "proposal": proposal, "original_contents": originals, "changed_files": changed,
        "intent": "CAPTURE", "text": "記録して", "summary": "デイリーへ1行追記します。",
        "spoken_reply": "追記しました。", "warnings": [],
    }
    return "job1"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_reject_leaves_every_vault_file_byte_identical(tmp_path: Path) -> None:
    vault, proposal, _ = _vault_with_proposal(tmp_path)
    app = create_app(_settings(tmp_path / "logs" / "operations.jsonl"), NO_SCHEME, vault)
    before = _snapshot(vault)

    with TestClient(app) as client:
        job = _pend(app, vault, proposal, ["01_daily/2026-09-01.md"])
        response = client.post(f"/jobs/{job}/reject")

    assert response.status_code == 200
    assert response.json()["applied"] is False
    assert _snapshot(vault) == before
    # 提案コピーは残さない。残すと次の承認で古い差分を適用しかねない
    assert not proposal.exists()


def test_approve_writes_only_the_changed_file(tmp_path: Path) -> None:
    vault, proposal, _ = _vault_with_proposal(tmp_path)
    app = create_app(_settings(tmp_path / "logs" / "operations.jsonl"), NO_SCHEME, vault)
    untouched = (vault / "keep.md").read_bytes()

    with TestClient(app) as client:
        job = _pend(app, vault, proposal, ["01_daily/2026-09-01.md"])
        response = client.post(f"/jobs/{job}/approve")

    assert response.status_code == 200
    assert response.json()["applied"] is True
    assert (vault / "01_daily" / "2026-09-01.md").read_text(encoding="utf-8") == "## 取り込み\n- 追記された1行\n"
    assert (vault / "keep.md").read_bytes() == untouched
    assert not proposal.exists()


def test_approve_is_refused_when_the_file_changed_after_the_proposal(tmp_path: Path) -> None:
    """§11-3「既存の未コミット変更を上書きしない」。提案後にユーザーが書いた場合。"""
    vault, proposal, _ = _vault_with_proposal(tmp_path)
    app = create_app(_settings(tmp_path / "logs" / "operations.jsonl"), NO_SCHEME, vault)

    with TestClient(app) as client:
        job = _pend(app, vault, proposal, ["01_daily/2026-09-01.md"])
        (vault / "01_daily" / "2026-09-01.md").write_text("## 取り込み\n- 本人が書いた\n", encoding="utf-8")
        response = client.post(f"/jobs/{job}/approve")

    assert response.status_code == 409
    assert (vault / "01_daily" / "2026-09-01.md").read_text(encoding="utf-8") == "## 取り込み\n- 本人が書いた\n"


def test_a_resolved_job_cannot_be_applied_twice(tmp_path: Path) -> None:
    vault, proposal, _ = _vault_with_proposal(tmp_path)
    app = create_app(_settings(tmp_path / "logs" / "operations.jsonl"), NO_SCHEME, vault)

    with TestClient(app) as client:
        job = _pend(app, vault, proposal, ["01_daily/2026-09-01.md"])
        assert client.post(f"/jobs/{job}/approve").status_code == 200
        assert client.post(f"/jobs/{job}/approve").status_code == 404
        assert client.post("/jobs/never-existed/reject").status_code == 404


def test_both_outcomes_are_written_to_the_operation_log(tmp_path: Path) -> None:
    """§11-10「全操作を logs/operations.jsonl に追記する」。"""
    vault, proposal, _ = _vault_with_proposal(tmp_path)
    log = tmp_path / "logs" / "operations.jsonl"
    app = create_app(_settings(log), NO_SCHEME, vault)

    with TestClient(app) as client:
        client.post(f"/jobs/{_pend(app, vault, proposal, ['01_daily/2026-09-01.md'])}/reject")

    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert len(entries) == 1
    assert entries[0]["approved"] is False
    assert entries[0]["reason"] == "rejected"
    assert entries[0]["changed_files"] == ["01_daily/2026-09-01.md"]
    assert entries[0]["intent"] == "CAPTURE"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_dirty_paths_lists_the_users_uncommitted_work(tmp_path: Path) -> None:
    """§11-1 実行前の git status。日本語パスも引用されず素で返る（-z）。"""
    repo = tmp_path / "vault"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "committed.md").write_text("a\n", encoding="utf-8")
    (repo / "日本語.md").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    (repo / "committed.md").write_text("b\n", encoding="utf-8")
    (repo / "日本語.md").write_text("b\n", encoding="utf-8")
    (repo / "untracked.md").write_text("new\n", encoding="utf-8")

    assert dirty_paths(repo) == {"committed.md", "日本語.md", "untracked.md"}


def test_dirty_paths_says_unknown_rather_than_clean_when_it_cannot_look(tmp_path: Path) -> None:
    """数えられないときに空集合を返すと、警告すべき場面で黙ってしまう。"""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert dirty_paths(plain) is None


def test_write_prompt_tells_the_agent_to_edit_its_copy() -> None:
    """コピーを実際に編集させないと差分が空になり、承認画面が出ない（§11）。"""
    from server.agent import build_prompt

    write = build_prompt("今日のことを記録して", "propose_write")
    assert "使い捨てコピー" in write
    assert "実際に書いて" in write
    assert "承認" in write
    assert "削除・移動・改名は禁止" in write

    read = build_prompt("今日の予定は？", "read_only")
    assert "読み取り専用" in read
    assert "使い捨てコピー" not in read


def test_prompt_states_the_answer_shape_for_backends_without_a_schema_flag() -> None:
    """codex は --output-schema で形を渡せるが、Claude Code には無い。
    どちらでも同じ JSON が返るよう、形はプロンプトにも書いておく（§2 の差し替え可能性）。"""
    from server.agent import build_prompt

    for mode in ("read_only", "propose_write"):
        prompt = build_prompt("今日の予定は？", mode)
        assert '"spoken_reply"' in prompt
        assert '"sources"' in prompt
        assert "コードフェンス" in prompt


def test_sandbox_values_come_from_the_environment(monkeypatch) -> None:
    """コード側に残っていた唯一の codex 固有部分。ここが差し替わらないと乗り換えられない。"""
    from server.agent import CodexAgent

    # server.config が load_dotenv() で .env を os.environ へ入れるので、
    # 既定を見るテストは環境を明示的に空にしてからでないと .env に左右される
    for name in ("AGENT_CMD", "CODEX_CMD", "AGENT_SANDBOX_READ", "AGENT_SANDBOX_WRITE"):
        monkeypatch.delenv(name, raising=False)
    default = CodexAgent(Path("/tmp/vault"))
    assert (default.sandbox_read, default.sandbox_write) == ("read-only", "workspace-write")

    monkeypatch.setenv("AGENT_SANDBOX_READ", '--allowedTools "Read,Glob,Grep"')
    monkeypatch.setenv("AGENT_SANDBOX_WRITE", "--permission-mode acceptEdits")
    monkeypatch.setenv("AGENT_CMD", "cd {cwd} && claude -p --output-format text {sandbox} > {out_file}")
    swapped = CodexAgent(Path("/tmp/vault"))
    assert swapped.sandbox_read == '--allowedTools "Read,Glob,Grep"'
    assert swapped.sandbox_write == "--permission-mode acceptEdits"
    assert swapped.command.startswith("cd {cwd} && claude")


def test_resume_command_comes_from_the_environment(monkeypatch) -> None:
    """AGENT_CMD を差し替えるとき、AGENT_RESUME_CMD も別に差し替えられること。
    既定は codex 用のままなので、Claude Code へ乗り換えるときは両方書き換える必要がある"""
    from server.agent import CodexAgent, DEFAULT_RESUME_CMD

    monkeypatch.delenv("AGENT_RESUME_CMD", raising=False)
    default = CodexAgent(Path("/tmp/vault"))
    assert default.resume_command == DEFAULT_RESUME_CMD

    monkeypatch.setenv("AGENT_RESUME_CMD", "claude -p --continue --output-format text > {out_file}")
    swapped = CodexAgent(Path("/tmp/vault"))
    assert swapped.resume_command.startswith("claude -p --continue")


def test_answer_survives_a_code_fence_or_a_stray_sentence(tmp_path: Path) -> None:
    """形は合っているのに1文字の余分で提案ごと捨てるのは損。
    --output-schema を持たない CLI では前後に文が付きやすい。"""
    from server.agent import CodexAgent

    body = '{"summary":"要約","spoken_reply":"読み上げ","sources":["a.md"]}'
    for name, raw in {
        "pure": body,
        "fenced": f"```json\n{body}\n```",
        "prose": f"追記しました。\n{body}\nご確認ください。",
    }.items():
        out = tmp_path / f"{name}.json"
        out.write_text(raw, encoding="utf-8")
        result = CodexAgent._parse(out)
        assert result.error is None, name
        assert result.spoken_reply == "読み上げ", name
        assert result.sources == ["a.md"], name


def test_a_brace_inside_a_string_does_not_cut_the_answer_short(tmp_path: Path) -> None:
    out = tmp_path / "a.json"
    out.write_text('{"summary":"} を含む要約","spoken_reply":"読み上げ","sources":[]}', encoding="utf-8")
    assert CodexAgent_parse_summary(out) == "} を含む要約"


def CodexAgent_parse_summary(out: Path) -> str:
    from server.agent import CodexAgent
    return CodexAgent._parse(out).summary


def test_unusable_output_still_reports_why(tmp_path: Path) -> None:
    """読めないときに黙って空を返さない（§17）。何が返ってきたかを残す。"""
    from server.agent import CodexAgent

    out = tmp_path / "a.json"
    out.write_text("すみません、できませんでした。", encoding="utf-8")
    result = CodexAgent._parse(out)
    assert result.error is not None
    assert "できませんでした" in result.error


# 会話の続き（2026-09-03）。ブートストラップと resume で別々のコマンドが
# 呼ばれることを、実際にサブプロセスを起動して確かめる。
# 中身に { } を含む JSON を書くコマンドは .format() の置換対象と衝突するので
# {{ }} で二重に括る（DEFAULT_CODEX_CMD 側は codex 自身の出力なのでこの問題が無い）
_BOOTSTRAP_CMD = "printf '%s' '{{\"summary\":\"boot\",\"spoken_reply\":\"boot\",\"sources\":[]}}' > {out_file}"
_RESUME_CMD = "printf '%s' '{{\"summary\":\"resume\",\"spoken_reply\":\"resume\",\"sources\":[]}}' > {out_file}"
_FAIL_CMD = "exit 1"


@_sync
async def test_second_read_only_turn_resumes_the_session(tmp_path: Path) -> None:
    """1回目はブートストラップ、2回目以降は resume を呼ぶ（本人の指定・2026-09-03：
    「タスク教えて」のあと「じゃあ1件目やって」のように話しかけられるように）。"""
    from server.agent import CodexAgent

    agent = CodexAgent(tmp_path, command=_BOOTSTRAP_CMD, resume_command=_RESUME_CMD)
    assert agent._session_started is False

    first = await agent.run("今日のタスク教えて", "read_only", use_session=True)
    assert first.summary == "boot"
    assert agent._session_started is True

    second = await agent.run("じゃあ1件目やって", "read_only", use_session=True)
    assert second.summary == "resume"


@_sync
async def test_propose_write_never_resumes(tmp_path: Path) -> None:
    """propose_write は毎回ちがう使い捨てコピーが作業ディレクトリになるので、
    use_session=True を渡しても resume の対象にしない。"""
    from server.agent import CodexAgent

    vault = tmp_path / "vault"
    vault.mkdir()
    agent = CodexAgent(vault, command=_BOOTSTRAP_CMD, resume_command=_RESUME_CMD)
    agent._session_started = True   # 会話が既に始まっている状態を作る

    result = await agent.run("直して", "propose_write", use_session=True)
    assert result.summary == "boot"   # resume ではなく毎回ブートストラップ


@_sync
async def test_a_lost_session_falls_back_to_bootstrap_next_time(tmp_path: Path) -> None:
    """resume 先のセッションが失われて失敗したら、次回はブートストラップからやり直す。
    直さないと、一度失われたセッションへ永遠に resume し続けて壊れたままになる。"""
    from server.agent import CodexAgent

    agent = CodexAgent(tmp_path, command=_BOOTSTRAP_CMD, resume_command=_FAIL_CMD)
    agent._session_started = True   # resume 先が既に無い状態を再現する

    failed = await agent.run("続き", "read_only", use_session=True)
    assert failed.error is not None
    assert agent._session_started is False

    recovered = await agent.run("続き", "read_only", use_session=True)
    assert recovered.summary == "boot"
