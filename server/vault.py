"""Vault を直接読んで答える（DESIGN.md §9 の ASK のうち、決まった問い）。

Codex を通すと実測 42.6 秒かかる（2026-08-31）。「今日のタスク」のような
決まった問いはファイルを読むだけで答えられるので、ここで返して即答する。

**読むだけ。書かない。** `_kit/AI_RULES.md` の「ファイルの削除・移動・改名を
しない」「ユーザーが書いた部分を書き換えない」に沿って、この層は読み取りしか
持たない（書き込みは Phase 4 の承認つき経路で扱う）。

答えられない問いは None を返す。**推測で埋めない。** 呼び出し側が Codex へ回す。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re


@dataclass
class Answer:
    summary: str            # 画面用
    spoken_reply: str       # 読み上げ用。80文字程度まで（§10）
    sources: list[str]      # 根拠にしたファイル。出典を言えるようにする


# デイリーの見出し。AI_RULES の「取り込み」「整理欄」は AI が書く欄なので、
# 「今日のタスク」への答えとしては本人が書いた欄を優先する
USER_SECTIONS = ("記録", "決めたこと", "覚えておいてほしいこと")


def _daily_path(vault: Path, day: date) -> Path:
    return vault / "01_daily" / f"{day.isoformat()}.md"


def _sections(text: str) -> dict[str, list[str]]:
    """`## 見出し` ごとに、中身の箇条書きを拾う。空欄（`- ` だけ）は落とす。"""
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            found.setdefault(current, [])
            continue
        if current is None:
            continue
        item = re.match(r"^\s*[-*]\s+(.*)$", line)
        if item and item.group(1).strip():
            found[current].append(item.group(1).strip())
    return found


def answer_today(vault: Path, today: date) -> Answer | None:
    """今日のデイリーから、本人が書いた欄を読む。無ければ「無い」と言う。"""
    path = _daily_path(vault, today)
    if not path.is_file():
        # AI_RULES「その日のデイリーが無い → 勝手に作らず、無いことを伝える」
        return Answer(
            summary=f"{today.isoformat()} のデイリーはまだありません。",
            spoken_reply="今日のデイリーはまだありません。",
            sources=[],
        )
    try:
        sections = _sections(path.read_text(encoding="utf-8"))
    except OSError:
        return None

    source = f"01_daily/{today.isoformat()}.md"
    lines: list[str] = []
    for name in USER_SECTIONS:
        items = sections.get(name, [])
        if items:
            lines.append(f"{name}: " + " / ".join(items))

    if not lines:
        return Answer(
            summary=f"{today.isoformat()} のデイリーはありますが、記録・決めたこと・覚えておいてほしいことは空です。",
            spoken_reply="今日のデイリーは、まだ何も書かれていません。",
            sources=[source],
        )

    spoken = lines[0]
    return Answer(
        summary="\n".join(lines),
        spoken_reply=_shorten(spoken),
        sources=[source],
    )


def answer_projects(vault: Path) -> Answer | None:
    """`00_home/home.md` の「続いているもの」を読む（索引が正。ここが起点）。"""
    home = vault / "00_home" / "home.md"
    try:
        sections = _sections(home.read_text(encoding="utf-8"))
    except OSError:
        return None
    items = sections.get("続いているもの", [])
    if not items:
        return None
    # `[[名前]] — 説明` から名前だけ取り出す
    names = [re.sub(r"^\**\[\[(.+?)\]\].*$", r"\1", i).split(" — ")[0].strip("* ") for i in items]
    return Answer(
        summary="続いているもの:\n" + "\n".join(f"・{i}" for i in items),
        spoken_reply=_shorten("続いているのは、" + "、".join(names[:4]) + "です。"),
        sources=["00_home/home.md"],
    )


def _shorten(text: str, limit: int = 80) -> str:
    """読み上げ用。§10「80文字程度まで」。切るときは切ったと分かる形にする。"""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def answer(vault: Path, topic: str, today: date | None = None) -> Answer | None:
    """topic に応じて直接答える。扱えない topic は None（Codex へ回す）。"""
    day = today or date.today()
    if topic == "today":
        return answer_today(vault, day)
    if topic == "projects":
        return answer_projects(vault)
    return None
