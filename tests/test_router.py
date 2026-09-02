"""用件判定と、Vault の直接読み取りの検証（DESIGN.md §9）。"""
from datetime import date
from pathlib import Path

from server.router import route
from server.vault import answer, answer_projects, answer_tasks, answer_today, open_tasks


def test_system_wins_over_everything() -> None:
    """§9「SYSTEM を最優先で判定する（エージェントを起動しない）」。"""
    # 「終わり」と「教えて」が両方入っていても SYSTEM
    assert route("もう終わりにして、あとで教えて").intent == "SYSTEM"
    assert route("ありがとう").intent == "SYSTEM"


def test_unknown_falls_back_to_ask() -> None:
    """§9「どれにも当たらなければ ASK を既定とする」。"""
    result = route("ふにゃふにゃ")
    assert result.intent == "ASK"
    assert result.mode == "read_only"


def test_write_intents_never_answer_directly() -> None:
    """書き込み系は承認が要る。直接答えて済ませてはいけない。"""
    for text in ("これを記録して", "スクリプトを作って"):
        result = route(text)
        assert result.mode == "propose_write"
        assert result.direct is None, f"{text} が直接応答へ回っている"


def test_today_question_is_answered_directly() -> None:
    """「今日のタスク」は Codex を通さない（実測 42.6 秒かかるため）。"""
    result = route("今日のタスクを教えて")
    assert result.intent == "ASK"
    assert result.direct == "tasks"


def test_today_tasks_are_not_confused_with_daily_decisions(tmp_path: Path) -> None:
    daily = tmp_path / "01_daily"
    daily.mkdir(parents=True)
    (daily / "2026-08-31.md").write_text("## 決めたこと\n- 投稿を止める\n", encoding="utf-8")
    projects = tmp_path / "02_projects"
    for number in range(1, 5):
        _project(projects, f"企画{number}", "active", [f"仕事{number}"])
    result = answer_tasks(tmp_path)
    assert result.summary.count(". [") == 3
    assert "投稿を止める" not in result.summary
    assert "仕事" in result.spoken_reply


def test_intent_records_what_matched() -> None:
    """§9「分類結果を字幕へ表示する（誤分類に気づけるようにする）」。"""
    assert route("今日のタスクを教えて").matched == "教えて"
    assert route("ふにゃふにゃ").matched == "(default)"


def test_missing_daily_says_so_instead_of_guessing(tmp_path: Path) -> None:
    """AI_RULES「その日のデイリーが無い → 勝手に作らず、無いことを伝える」。"""
    (tmp_path / "01_daily").mkdir(parents=True)
    result = answer_today(tmp_path, date(2026, 8, 31))
    assert result is not None
    assert "まだないよ" in result.spoken_reply
    assert result.sources == [], "無いファイルを出典に挙げない"


def test_empty_daily_is_not_reported_as_content(tmp_path: Path) -> None:
    """空欄を「書いてある」と言わない。`- ` だけの行は中身ではない。"""
    daily = tmp_path / "01_daily"
    daily.mkdir(parents=True)
    (daily / "2026-08-31.md").write_text(
        "# 2026-08-31\n\n## 記録\n- \n\n## 決めたこと\n- \n", encoding="utf-8")
    result = answer_today(tmp_path, date(2026, 8, 31))
    assert result is not None
    # 空だと言う。**空欄の `- ` を中身として読み上げない**（ここがこの試験の主旨）
    assert "空" in result.spoken_reply
    assert "記録:" not in result.summary


def test_daily_content_is_read_from_the_user_sections(tmp_path: Path) -> None:
    daily = tmp_path / "01_daily"
    daily.mkdir(parents=True)
    (daily / "2026-08-31.md").write_text(
        "# 2026-08-31\n\n## 記録\n- 朝に散歩した\n\n"
        "## 決めたこと\n- JARVISを完成させる\n\n"
        "## 取り込み（AIが書く）\n- これはAIの欄なので拾わない\n",
        encoding="utf-8")
    result = answer_today(tmp_path, date(2026, 8, 31))
    assert result is not None
    assert "朝に散歩した" in result.summary
    assert "JARVISを完成させる" in result.summary
    assert "これはAIの欄" not in result.summary, "AIが書く欄まで答えに混ぜている"
    assert result.sources == ["01_daily/2026-08-31.md"]


def test_spoken_reply_stays_short(tmp_path: Path) -> None:
    """§10「読み上げ用。80文字程度まで」。長い記録でも読み上げは切る。"""
    daily = tmp_path / "01_daily"
    daily.mkdir(parents=True)
    (daily / "2026-08-31.md").write_text(
        "## 記録\n- " + "あ" * 300 + "\n", encoding="utf-8")
    result = answer_today(tmp_path, date(2026, 8, 31))
    assert result is not None
    assert len(result.spoken_reply) <= 80


def test_projects_come_from_the_index(tmp_path: Path) -> None:
    """AI_RULES「home.md は索引。必ず読む」。プロジェクトはここを起点にする。"""
    home = tmp_path / "00_home"
    home.mkdir(parents=True)
    (home / "home.md").write_text(
        "# home\n\n## 続いているもの\n"
        "- [[jarvis-secretary]] — iPhoneを常設AI秘書にする\n"
        "- [[HyperFrames]] — 3媒体へ配信中\n", encoding="utf-8")
    result = answer_projects(tmp_path)
    assert result is not None
    assert "jarvis-secretary" in result.spoken_reply
    assert result.sources == ["00_home/home.md"]


def test_unknown_topic_returns_none(tmp_path: Path) -> None:
    """扱えない問いは None。ここで作り話をせず、呼び出し側が Codex へ回す。"""
    assert answer(tmp_path, "なんだかよく分からない話") is None


def test_long_tasks_get_flagged() -> None:
    """記事の執筆や調べ物は分単位かかる。持ち時間を延ばす目印を立てる（2026-09-02）。"""
    assert route("JARVISの設計書のnote記事を書いて").long is True
    assert route("競合をリサーチして").long is True
    assert route("サムネを作って").long is True
    # 短い問いは延長しない。即答できるものを待たせない
    assert route("今日のタスクは？").long is False
    assert route("ありがとう").long is False


def test_long_tasks_never_take_the_direct_shortcut() -> None:
    """「今日の記録をまとめて」を、デイリーの読み上げで済ませてしまわない。

    direct は即答用の表なので、時間のかかる仕事に当てると
    「まとめて」と頼んだのに読み上げただけ、という取り違えが起きる。
    """
    result = route("今日の記録をまとめて")
    assert result.long is True
    assert result.direct is None


def test_stop_words_still_route_to_system_while_busy() -> None:
    """割り込みの口。考えている最中でも「やめて」は SYSTEM へ落ちる必要がある。"""
    for word in ("やめて", "キャンセル", "終わり"):
        assert route(word).intent == "SYSTEM"


def _project(folder: Path, name: str, status: str, items: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- [ ] {i}" for i in items)
    (folder / f"{name}.md").write_text(
        f"---\ntype: project\nstatus: {status}\n---\n\n# {name}\n\n"
        f"## 次にやること\n{body}\n", encoding="utf-8")


def test_open_tasks_only_from_active_projects(tmp_path: Path) -> None:
    """`status: active` だけを見る。paused / idea は今日の候補ではない。"""
    projects = tmp_path / "02_projects"
    _project(projects, "動いてるもの", "active", ["最初の仕事", "次の仕事"])
    _project(projects, "止めたもの", "paused", ["これは出ない"])
    _project(projects, "思いつき", "idea", ["これも出ない"])
    tasks = open_tasks(tmp_path)
    assert [t.text for t in tasks] == ["最初の仕事", "次の仕事"]
    assert {t.project for t in tasks} == {"動いてるもの"}


def test_open_tasks_skip_finished_items(tmp_path: Path) -> None:
    """`- [x]` は未完了ではない。終わったものを今日の候補にしない。"""
    projects = tmp_path / "02_projects"
    projects.mkdir(parents=True)
    (projects / "p.md").write_text(
        "---\nstatus: active\n---\n\n## 次にやること\n"
        "- [x] 終わった\n- [ ] まだ\n", encoding="utf-8")
    assert [t.text for t in open_tasks(tmp_path)] == ["まだ"]


def test_open_tasks_only_from_the_task_section(tmp_path: Path) -> None:
    """`## 次にやること` の外にあるチェックボックスは拾わない。

    受け入れ条件や設計メモにも `- [ ]` は出てくる。全部集めると
    「今日やること」が設計書の目次になる（2026-09-02、実際に混ざっていた）。
    """
    projects = tmp_path / "02_projects"
    projects.mkdir(parents=True)
    (projects / "p.md").write_text(
        "---\nstatus: active\n---\n\n"
        "## 受け入れ条件\n- [ ] これは仕事ではない\n\n"
        "## 次にやること\n- [ ] これが仕事\n", encoding="utf-8")
    assert [t.text for t in open_tasks(tmp_path)] == ["これが仕事"]


def test_empty_daily_falls_back_to_open_tasks(tmp_path: Path) -> None:
    """デイリーが空でも「何もありません」で終わらせない。

    朝の欄は空から始まる。そこで打ち切ると「今日のタスクは？」が毎朝使えない
    （2026-09-02）。続いている仕事のほうを答える。
    """
    daily = tmp_path / "01_daily"
    daily.mkdir(parents=True)
    (daily / "2026-08-31.md").write_text("# 2026-08-31\n\n## 記録\n- \n", encoding="utf-8")
    _project(tmp_path / "02_projects", "続いてる企画", "active", ["これをやる"])

    result = answer_today(tmp_path, date(2026, 8, 31))
    assert result is not None
    assert "1件" in result.spoken_reply           # 件数を先に言う
    assert "これをやる" in result.summary
    assert "02_projects/続いてる企画.md" in result.sources


def test_missing_daily_still_answers_with_open_tasks(tmp_path: Path) -> None:
    """デイリーが無い日でも、続いている仕事は答えられる。勝手に作りはしない。"""
    _project(tmp_path / "02_projects", "企画", "active", ["残っている仕事"])
    result = answer_today(tmp_path, date(2026, 8, 31))
    assert result is not None
    assert "デイリーはまだないよ" in result.summary
    assert "残っている仕事" in result.summary
    assert not (tmp_path / "01_daily").exists()   # AI_RULES「勝手に作らない」


def test_clap_fixed_question_always_goes_through_codex() -> None:
    """拍手で送る固定質問（なにする？）は、先読みキャッシュへ即座に乗せず
    毎回 Codex を実際に起動して Vault を読ませる（2026-09-02、本人の指定）。
    一度は逆に「先読みへ即答させるべき」と直したが、本人はそれを望んでいなかった。"""
    result = route("なにする？")
    assert result.intent == "ASK"
    assert result.direct is None
