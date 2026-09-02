"""先読みブリーフィングの検証（2026-09-02）。

ここで確かめるのは**配管**であって、LLM の答えの質ではない。
「キャッシュが無い／古い／作成中に本人が来た」ときに壊れないことを見る。
"""
import asyncio
from functools import wraps
from pathlib import Path

import pytest

from server.agent import AgentResult
from server.briefing import FRESH_S, Briefing, _fingerprint, build_prompt
from server.vault import OpenTask


def _sync(test):
    """非同期のテストを普通のテストとして回す。

    このリポジトリには async テストが無く、pytest の非同期プラグイン設定も
    入っていない。ここ1本のために設定を足すより、asyncio.run で包むほうが軽い。
    """
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


class FakeAgent:
    """呼ばれた回数と、返す中身を差し替えられるだけの替え玉。"""

    def __init__(self, result: AgentResult | None = None, delay: float = 0) -> None:
        self.result = result or AgentResult("画面用のまとめ", "読み上げ用", sources=["02_projects/p.md"])
        self.delay = delay
        self.calls = 0
        self.started = asyncio.Event()

    async def run(self, text: str, mode: str = "read_only", timeout: int | None = None) -> AgentResult:
        self.calls += 1
        self.started.set()
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


def _vault(tmp_path: Path, items: list[str]) -> Path:
    projects = tmp_path / "02_projects"
    projects.mkdir(parents=True)
    body = "\n".join(f"- [ ] {i}" for i in items)
    (projects / "p.md").write_text(
        f"---\nstatus: active\n---\n\n## 次にやること\n{body}\n", encoding="utf-8")
    return tmp_path


def test_no_cache_returns_none(tmp_path: Path) -> None:
    """まだ作っていなければ None。**ここで作り話をしない**（機械読みへ落とす）。"""
    assert Briefing(_vault(tmp_path, ["仕事"]), FakeAgent()).answer() is None


@_sync
async def test_refresh_caches_the_answer(tmp_path: Path) -> None:
    agent = FakeAgent()
    brief = Briefing(_vault(tmp_path, ["仕事"]), agent)
    await brief._refresh()
    ready = brief.answer()
    assert ready is not None
    assert ready.spoken_reply == "読み上げ用"
    assert ready.sources == ["02_projects/p.md"]


@_sync
async def test_no_open_tasks_means_no_llm_call(tmp_path: Path) -> None:
    """候補が無いのに LLM を呼ばない。空の Vault で毎分 94 秒の仕事を始めない。"""
    (tmp_path / "02_projects").mkdir(parents=True)
    agent = FakeAgent()
    await Briefing(tmp_path, agent)._refresh()
    assert agent.calls == 0


@_sync
async def test_agent_error_leaves_no_cache(tmp_path: Path) -> None:
    """作成に失敗しても黙って諦める。機械読みが答えるので会話は成立する。"""
    agent = FakeAgent(AgentResult("", "", error="AGENT_TIMEOUT (120s)"))
    brief = Briefing(_vault(tmp_path, ["仕事"]), agent)
    await brief._refresh()
    assert brief.answer() is None


@_sync
async def test_stale_answer_says_how_old_it_is(tmp_path: Path) -> None:
    """古い答えを「今の話」として言わない。**経過を添えれば嘘にならない**。"""
    brief = Briefing(_vault(tmp_path, ["仕事"]), FakeAgent())
    await brief._refresh()
    brief._cached.at -= FRESH_S + 3600      # 1時間ぶん余計に古くする
    ready = brief.answer()
    assert ready is not None
    assert "時間前" in ready.spoken_reply
    assert "時間前" in ready.summary


@_sync
async def test_user_request_cancels_the_background_build(tmp_path: Path) -> None:
    """本人の依頼が最優先。裏の作成は譲る。

    エージェントは同時1ジョブなので、譲らないと本人が裏の仕事の終わり
    （実測 94 秒）を待たされる。
    """
    agent = FakeAgent(delay=30)
    brief = Briefing(_vault(tmp_path, ["仕事"]), agent)
    brief._task = asyncio.create_task(brief._refresh())
    await asyncio.wait_for(agent.started.wait(), timeout=5)

    brief.yield_to_user()
    with pytest.raises(asyncio.CancelledError):
        await brief._task
    assert brief.answer() is None


def test_fingerprint_only_watches_files_that_change_the_judgement(tmp_path: Path) -> None:
    """Vault 全体を舐めない。判断に効くものだけ見る。

    資料や下書きが変わるたびに 94 秒の仕事を始めると、本人の依頼が
    ずっと譲られ続ける（同時1ジョブなので）。
    """
    vault = _vault(tmp_path, ["仕事"])
    (vault / "04_resources").mkdir()
    before = _fingerprint(vault)

    (vault / "04_resources" / "調べもの.md").write_text("関係ない", encoding="utf-8")
    assert _fingerprint(vault) == before, "資料の更新で作り直している"

    (vault / "02_projects" / "p.md").write_text(
        "---\nstatus: active\n---\n\n## 次にやること\n- [ ] 変わった\n", encoding="utf-8")
    assert _fingerprint(vault) != before, "プロジェクトの更新を見落としている"


def test_prompt_carries_the_candidates_so_the_agent_need_not_search() -> None:
    """候補集めは済んでいる。探させないぶん速く、根拠も外さない。"""
    prompt = build_prompt([OpenTask("企画", "最初の仕事"), OpenTask("企画", "次の仕事")])
    assert "最初の仕事" in prompt and "次の仕事" in prompt
    assert "2件" in prompt
    assert "出典が言えないことは書かないでください" in prompt
