"""用件判定と、Vault の直接読み取りの検証（DESIGN.md §9）。"""
from datetime import date
from pathlib import Path

from server.router import route
from server.vault import answer, answer_projects, answer_today


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
    assert result.direct == "today"


def test_intent_records_what_matched() -> None:
    """§9「分類結果を字幕へ表示する（誤分類に気づけるようにする）」。"""
    assert route("今日のタスクを教えて").matched == "教えて"
    assert route("ふにゃふにゃ").matched == "(default)"


def test_missing_daily_says_so_instead_of_guessing(tmp_path: Path) -> None:
    """AI_RULES「その日のデイリーが無い → 勝手に作らず、無いことを伝える」。"""
    (tmp_path / "01_daily").mkdir(parents=True)
    result = answer_today(tmp_path, date(2026, 8, 31))
    assert result is not None
    assert "ありません" in result.spoken_reply
    assert result.sources == [], "無いファイルを出典に挙げない"


def test_empty_daily_is_not_reported_as_content(tmp_path: Path) -> None:
    """空欄を「書いてある」と言わない。`- ` だけの行は中身ではない。"""
    daily = tmp_path / "01_daily"
    daily.mkdir(parents=True)
    (daily / "2026-08-31.md").write_text(
        "# 2026-08-31\n\n## 記録\n- \n\n## 決めたこと\n- \n", encoding="utf-8")
    result = answer_today(tmp_path, date(2026, 8, 31))
    assert result is not None
    assert "まだ何も" in result.spoken_reply


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
