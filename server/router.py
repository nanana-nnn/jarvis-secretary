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

# WALLPAPER は PC の見た目を変える操作（2026-09-05）。Vault とも Codex とも
# 関係がないので、判定の一番手前で分けて、専用の画面（スライダー）へ渡す
Intent = Literal["SYSTEM", "WALLPAPER", "CAPTURE", "EXECUTE", "DECIDE", "ASK"]
Mode = Literal["read_only", "propose_write"]

# 直接答えられる問い。ここに当たれば Codex を起動しない
DirectTopic = Literal["tasks", "today", "recent", "projects", "status", "vault"]


@dataclass(frozen=True)
class Route:
    intent: Intent
    mode: Mode
    direct: DirectTopic | None      # None なら Codex へ回す
    matched: str                    # 何に当たったか。誤分類に気づけるよう画面へ出す
    long: bool = False              # 既定の持ち時間では終わらない仕事か（§10）


# 壁紙を選びたい合図。**RULES より先に見る。**
# 「壁紙変えて」は EXECUTE の「変えて」に当たってしまい、Codex に Vault を
# 書き換えさせる話になってしまう（2026-09-05）。ここで先に捕まえる
WALLPAPER_WORDS: tuple[str, ...] = ("壁紙", "背景", "かべがみ")

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
    # 「今日のタスク」は **直答しない**（2026-09-04、本人の指定）。
    # 話しかける→PC画面で作業する様子が見える→結果だけスマホに返る、を
    # SNS用に優先した。直答は0秒で返る代わりに Codex を起動せず、画面に
    # 何も出ない。ここに戻すと速くなるが、その絵は撮れなくなる。
    # （2026-09-03 は逆に「30秒待たされる」としてここへ足していた）
    ("today",    ("今日の記録", "今日のデイリー")),
    ("recent",   ("最近", "この前", "昨日", "直近")),
    ("projects", ("プロジェクト", "進行中", "続いているもの", "案件")),
    ("status",   ("状態", "進捗", "どこまで", "どうなってる")),
    ("vault",    ("未コミット", "コミットして", "git")),
]

# 既定の持ち時間（120秒）では終わらない仕事。記事の執筆や調べ物は分単位かかる。
# ここに当たると持ち時間を延ばし、進捗を送りながら待つ（§10）。
# **能力ではなく時間の話。** 何ができるかはサンドボックスの設定で決まる
LONG_TASK: tuple[str, ...] = (
    "記事", "note", "ノート記事", "下書き", "サムネ",
    "リサーチ", "調べて", "調査", "まとめて", "書き上げ", "構成",
)


def route(text: str) -> Route:
    """発話を分類する。どれにも当たらなければ §9 のとおり ASK を既定にする。"""
    normalised = text.strip()
    long = _is_long(normalised)

    # 壁紙は RULES より先。下の EXECUTE（「変えて」）に食われないようにする
    for word in WALLPAPER_WORDS:
        if word in normalised:
            return Route(intent="WALLPAPER", mode="read_only", direct=None, matched=word)

    for intent, mode, keywords in RULES:
        for keyword in keywords:
            if keyword in normalised:
                # 読み取り専用の問いだけ、直接答えられるか見る。
                # 書き込み系(CAPTURE/EXECUTE)は承認が要るので必ずエージェントへ回す
                direct = _direct_topic(normalised) if intent in ("ASK", "DECIDE") else None
                # 時間のかかる仕事は即答の表に当てない。「今日の記録をまとめて」を
                # デイリーの読み上げで済ませてしまわないようにする
                if long:
                    direct = None
                return Route(intent=intent, mode=mode, direct=direct, matched=keyword, long=long)

    # §9「どれにも当たらなければ ASK を既定とする」
    return Route(intent="ASK", mode="read_only",
                 direct=None if long else _direct_topic(normalised),
                 matched="(default)", long=long)


def _is_long(text: str) -> bool:
    return any(keyword in text for keyword in LONG_TASK)


def _direct_topic(text: str) -> DirectTopic | None:
    for topic, keywords in DIRECT:
        for keyword in keywords:
            if keyword in text:
                return topic
    return None
