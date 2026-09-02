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


@dataclass(frozen=True)
class OpenTask:
    project: str            # プロジェクト名（ファイル名から）
    text: str               # 項目の1行目。続きの行は読み上げに要らない


# デイリーの見出し。AI_RULES の「取り込み」「整理欄」は AI が書く欄なので、
# 「今日のタスク」への答えとしては本人が書いた欄を優先する
USER_SECTIONS = ("記録", "決めたこと", "覚えておいてほしいこと")

# プロジェクトの未完了を置く見出し。Vault の型（`_kit/SPEC.md`）に沿う
TASK_SECTION = "次にやること"


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
    """今日のデイリーから、本人が書いた欄を読む。

    デイリーが空でも「何も書かれていません」で終わらせない。**その日の欄が
    空なのは普通のこと**（朝は空から始まる）で、そこで打ち切ると
    「今日のタスクは？」が毎朝使えない（2026-09-02）。
    書かれていなければ、進行中プロジェクトの未完了を候補として返す。
    """
    path = _daily_path(vault, today)
    if not path.is_file():
        # AI_RULES「その日のデイリーが無い → 勝手に作らず、無いことを伝える」
        # ただし「無い」で終わらせず、続いている仕事のほうを答える
        return _from_open_tasks(vault, f"{today.isoformat()} のデイリーはまだありません。")
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
        return _from_open_tasks(vault, "今日のデイリーはまだ空です。", extra_source=source)

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


def _from_open_tasks(vault: Path, preface: str, extra_source: str | None = None) -> Answer:
    """デイリーに書かれていないとき、続いている仕事のほうを答える。

    件数を先に言う。60件あるものを上から3つ読み上げても選んだことにならないので、
    **全体の量と、直近のプロジェクトだけ**を伝えて、続きは画面に出す。
    """
    tasks = open_tasks(vault)
    if not tasks:
        return Answer(summary=preface, spoken_reply=preface, sources=[extra_source] if extra_source else [])

    projects: list[str] = []
    for task in tasks:
        if task.project not in projects:
            projects.append(task.project)
    head = tasks[:8]
    summary = preface + f"\n進行中の未完了は{len(tasks)}件（{len(projects)}プロジェクト）。\n" + \
        "\n".join(f"・[{t.project}] {t.text}" for t in head)
    if len(tasks) > len(head):
        summary += f"\n…ほか{len(tasks) - len(head)}件"
    spoken = _shorten(preface + f"進行中の未完了が{len(tasks)}件あります。"
                      + "、".join(projects[:3]) + "などです。")
    sources = [f"02_projects/{name}.md" for name in projects]
    if extra_source:
        sources.insert(0, extra_source)
    return Answer(summary=summary, spoken_reply=spoken, sources=sources)


def _status(text: str) -> str | None:
    """frontmatter の `status:` を読む。無ければ None。"""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    found = re.search(r"^status:\s*(\S+)\s*$", text[:end], re.MULTILINE)
    return found.group(1) if found else None


def open_tasks(vault: Path) -> list[OpenTask]:
    """`status: active` のプロジェクトから、未チェックの「次にやること」を集める。

    **LLM を通さない。** Vault は既に構造を持っている（frontmatter の status と
    `- [ ]`）ので、候補を集めるだけならファイルを読めば足りる。0秒で返せる。
    どれが今日の仕事かという判断だけが LLM の仕事（2026-09-02）。

    書いてあるものをそのまま返す。**古ければ古いまま返す。**
    実態と違えば読み上げた本人が気づく。ここで推測して補わない。
    """
    folder = vault / "02_projects"
    if not folder.is_dir():
        return []
    tasks: list[OpenTask] = []
    for path in sorted(folder.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _status(text) != "active":
            continue
        in_section = False
        for line in text.splitlines():
            heading = re.match(r"^##\s+(.+?)\s*$", line)
            if heading:
                in_section = heading.group(1) == TASK_SECTION
                continue
            if not in_section:
                continue
            item = re.match(r"^\s*[-*]\s+\[ \]\s+(.+?)\s*$", line)
            if item:
                tasks.append(OpenTask(project=path.stem, text=item.group(1)))
    return tasks


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
