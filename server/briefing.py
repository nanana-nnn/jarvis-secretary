"""「今日のタスクは？」の答えを、聞かれる前に作っておく。

**聞かれてから作ると 42.6 秒かかる**（2026-08-31 実測）。秘書として成立しない。
だがこの問いの答えは、聞かれた瞬間に決まるものではない。Vault が変わった時点で
決まっている。**だから聞かれる前に作る。**

仕事を2つに割る（2026-09-02 決定）:

    候補を集める   status: active × `## 次にやること` の未チェック   0秒・LLM不要
    どれが今日か    60件のうちどれを今日やるかの判断                 ここだけLLM

この層は後者だけを扱う。前者は `vault.open_tasks()` が常に即答するので、
**キャッシュが無くても・古くても、答えは必ず返る**（機械読みへ落ちる）。

作り直す時機:
  - サーバー起動時
  - Vault のファイルが変わったとき（1分ごとに mtime を見る）

**利用者の発話が最優先。** 裏で走っている作成は、本人の依頼が来たら譲る
（エージェントは同時1ジョブなので、譲らないと本人が裏の仕事を待たされる）。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from time import monotonic

from . import vault as vault_reader

logger = logging.getLogger("uvicorn.error")

# Vault の変化を見にいく間隔。配色・壁紙の監視（1秒）より粗くてよい。
# 書きかけの1文字ごとに作り直しても、判断は変わらない
WATCH_EVERY_S = 60

# 作った答えを「今の話」として扱ってよい時間。これを過ぎたら経過を添えて言う
FRESH_S = 3 * 60 * 60


@dataclass
class Cached:
    summary: str
    spoken_reply: str
    sources: list[str]
    at: float                 # monotonic。作った時刻


def _fingerprint(vault: Path) -> tuple:
    """判断に効くファイルの更新時刻。ここが変われば作り直す。

    Vault 全体を舐めない。**判断に使うものだけ**を見る
    （デイリー・プロジェクト・索引）。
    """
    marks: list[tuple[str, float]] = []
    for folder, pattern in (("01_daily", "*.md"), ("02_projects", "*.md"), ("00_home", "home.md")):
        directory = vault / folder
        if not directory.is_dir():
            continue
        for path in directory.glob(pattern):
            try:
                marks.append((path.name, path.stat().st_mtime))
            except OSError:
                continue
    return tuple(sorted(marks))


def build_prompt(tasks: list[vault_reader.OpenTask]) -> str:
    """判断だけを頼む。候補集めは済んでいるので、探させない（そのぶん速い）。"""
    listing = "\n".join(f"- [{t.project}] {t.text}" for t in tasks)
    return f"""あなたはこの Obsidian Vault の持ち主の秘書です。

進行中プロジェクトの未完了は次の{len(tasks)}件です。

{listing}

この中から**今日やるべき上位3件**を選んでください。
選ぶ根拠は Vault の記録（プロジェクトの状態、直近のデイリー、03_memory の判断）に
求めてください。**出典が言えないことは書かないでください。**
迷ったら、期日があるもの・他がつかえているもの・書いた本人が繰り返し触れているものを優先します。

最終メッセージは次のJSONだけを返してください。前後に説明やコードフェンスを付けないでください。
{{"summary":"画面用。3件を根拠つきで(日本語)","spoken_reply":"読み上げ用(日本語80文字程度)","sources":["根拠にしたVault内のファイルパス"]}}
"""


class Briefing:
    """先読みしたブリーフィング。無ければ機械読みへ落ちるので、失敗しても壊れない。"""

    def __init__(self, vault: Path, agent) -> None:
        self.vault = vault
        self.agent = agent
        self._cached: Cached | None = None
        self._fingerprint: tuple | None = None
        self._task: asyncio.Task | None = None

    def answer(self) -> vault_reader.Answer | None:
        """キャッシュがあれば返す。**古ければ古いと言う。** 無ければ None。"""
        if self._cached is None:
            return None
        age = monotonic() - self._cached.at
        summary, spoken = self._cached.summary, self._cached.spoken_reply
        if age > FRESH_S:
            hours = int(age // 3600)
            summary = f"（{hours}時間前の時点）\n" + summary
            spoken = f"{hours}時間前の時点では、" + spoken
        return vault_reader.Answer(summary=summary, spoken_reply=spoken, sources=list(self._cached.sources))

    def yield_to_user(self) -> None:
        """本人の依頼が来た。裏の作成は譲る（同時1ジョブなので待たせてしまう）。"""
        if self._task is not None and not self._task.done():
            logger.info("[BRIEF] yielding to user request")
            self._task.cancel()

    async def watch(self) -> None:
        """起動時に1回作り、以降は Vault が変わったら作り直す。"""
        while True:
            try:
                mark = await asyncio.to_thread(_fingerprint, self.vault)
                if mark != self._fingerprint:
                    self._fingerprint = mark
                    if self._task is None or self._task.done():
                        self._task = asyncio.create_task(self._refresh())
            except Exception:                       # 先読みで本体を落とさない
                logger.exception("[BRIEF] watch failed")
            await asyncio.sleep(WATCH_EVERY_S)

    async def _refresh(self) -> None:
        tasks = await asyncio.to_thread(vault_reader.open_tasks, self.vault)
        if not tasks:
            self._cached = None
            return
        logger.info("[BRIEF] building from %d open tasks", len(tasks))
        started = monotonic()
        try:
            outcome = await self.agent.run(build_prompt(tasks), "read_only")
        except asyncio.CancelledError:
            logger.info("[BRIEF] cancelled")
            raise
        if outcome.error:
            # 作れなくても機械読みが答えるので、ここは黙って諦めてよい
            logger.warning("[BRIEF] %s", outcome.error)
            return
        self._cached = Cached(
            summary=outcome.summary,
            spoken_reply=outcome.spoken_reply,
            sources=list(outcome.sources),
            at=monotonic(),
        )
        logger.info("[BRIEF] ready in %.1fs", monotonic() - started)
