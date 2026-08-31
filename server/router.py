"""用件の判定（DESIGN.md §9「ルーター」）。

**LLM を使わないルールベース。** キーワードは下の表に持つ。

§9 の分類に加えて、実装では `direct` を持たせている。
「今日のタスク」のような決まった問いは、Codex を通さずサーバーが Vault を
読んで返す。Codex に投げると実測 42.6 秒かかり、秘書として成立しないため
（2026-08-31 実測）。複雑な問いだけ Codex へ回す。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Intent = Literal["SYSTEM", "CAPTURE", "EXECUTE", "DECIDE", "ASK"]
Mode = Literal["read_only", "propose_write"]

# 直接答えられる問い。ここに当たれば Codex を起動しない
DirectTopic = Literal["today", "recent", "projects", "status", "vault"]


@dataclass(frozen=True)
class Route:
    intent: Intent
    mode: Mode
    direct: DirectTopic | None      # None なら Codex へ回す
    matched: str                    # 何に当たったか。誤分類に気づけるよう画面へ出す


# §9 の表。左が分類、右が手がかり。**上から順に見る**（SYSTEM が最優先）
RULES: list[tuple[Intent, Mode, tuple[str, ...]]] = [
    ("SYSTEM",  "read_only",     ("音量", "再接続", "寝て", "おやすみ", "終わり", "ありがとう", "やめて", "キャンセル")),
    ("CAPTURE", "propose_write", ("記録して", "残して", "メモして", "書いて", "追記")),
    ("EXECUTE", "propose_write", ("作って", "直して", "実装して", "修正して", "変えて")),
    ("DECIDE",  "read_only",     ("どっち", "優先", "決めて", "軍配", "選んで")),
    ("ASK",     "read_only",     ("何", "なに", "どこ", "教えて", "状態", "どうなってる", "ある?", "ありますか")),
]

# 直接答える問い。ASK のうち、決まった読み方で足りるもの。
# 長い言い回しから先に見る（「今日の予定」より先に「今日のタスク」を当てる）
DIRECT: list[tuple[DirectTopic, tuple[str, ...]]] = [
    ("today",    ("今日のタスク", "今日の予定", "今日やること", "今日の記録", "今日のデイリー", "今日は何")),
    ("recent",   ("最近", "この前", "昨日", "直近")),
    ("projects", ("プロジェクト", "進行中", "続いているもの", "案件")),
    ("status",   ("状態", "進捗", "どこまで", "どうなってる")),
    ("vault",    ("未コミット", "コミットして", "git")),
]


def route(text: str) -> Route:
    """発話を分類する。どれにも当たらなければ §9 のとおり ASK を既定にする。"""
    normalised = text.strip()

    for intent, mode, keywords in RULES:
        for keyword in keywords:
            if keyword in normalised:
                # 読み取り専用の問いだけ、直接答えられるか見る。
                # 書き込み系(CAPTURE/EXECUTE)は承認が要るので必ずエージェントへ回す
                direct = _direct_topic(normalised) if intent in ("ASK", "DECIDE") else None
                return Route(intent=intent, mode=mode, direct=direct, matched=keyword)

    # §9「どれにも当たらなければ ASK を既定とする」
    return Route(intent="ASK", mode="read_only", direct=_direct_topic(normalised), matched="(default)")


def _direct_topic(text: str) -> DirectTopic | None:
    for topic, keywords in DIRECT:
        for keyword in keywords:
            if keyword in text:
                return topic
    return None
