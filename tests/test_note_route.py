"""「noteを書いて」と言われたら下書きまで運ぶ経路の検証（2026-09-05）。

ここで確かめるのは**配管**であって、Codex が書く文章の質ではない。
「Vault を変えないこと」「公開に触れないこと」「失敗を成功と言わないこと」を見る。
"""
import asyncio
import json
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest

from server import note_writer
from server.agent import AgentResult, CodexAgent, build_prompt, schema_for
from server.router import route
from server.session import Session


def _sync(test):
    """非同期のテストを普通のテストとして回す（pytest-asyncio を足さずに済ませる）。"""
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


# --- ルーター -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "JARVISのnote書いて",
    "JARVISの設計書をnoteに書いて",
    "note記事書いて",
])
def test_noteを頼まれたらCAPTUREに食われない(text):
    """「書いて」は CAPTURE の手がかりでもある。**note が先に当たること。**
    CAPTURE に落ちると Codex が Vault を書き換える提案を出してしまう。"""
    decision = route(text)
    assert decision.intent == "NOTE", text
    assert decision.mode == "note"
    assert decision.long is True          # 分単位かかるので経過を送る側へ回す


@pytest.mark.parametrize("text", ["今日のデイリーノートに書いて", "ノートに残して", "記録して"])
def test_Vaultのノートはnote扱いにしない(text):
    """Obsidian の「ノート」を note の下書きにしない。ここが混ざると
    記録を頼んだだけで note に記事ができる。"""
    assert route(text).intent != "NOTE", text


# --- エージェント ---------------------------------------------------------

def test_noteのプロンプトは読み取り専用で出典を求める():
    prompt = build_prompt("JARVISのnote書いて", "note")
    assert "ファイルを一切変更しないでください" in prompt
    assert "出典が言えないことを書かない" in prompt
    assert "JARVISのnote書いて" in prompt


def test_noteのテスト依頼はCodexの画面表示を使う():
    prompt = build_prompt("noteのテストしてサムネも", "note")
    assert "読み取り専用" in prompt


def test_noteのテスト依頼は200字前後を指定する():
    prompt = build_prompt("noteのテストして", "note")
    assert "180〜220文字" in prompt


def test_noteのスキーマだけ題と本文を持つ():
    assert set(schema_for("note")["required"]) == {"title", "body", "spoken_reply", "sources"}
    assert "title" not in schema_for("read_only")["properties"]


def test_題か本文が空なら失敗にする(tmp_path):
    """片方だけで進めると note に中途半端な記事が残る。作り直さない規則が
    あるので取り返せない。**空は必ず失敗にする。**"""
    out = tmp_path / "answer.json"
    out.write_text(json.dumps({"title": "題だけ", "body": "", "spoken_reply": "はい", "sources": []}),
                   encoding="utf-8")
    result = CodexAgent._parse(out, "note")
    assert result.error is not None and result.title == ""


def test_題と本文が揃えば取り出せる(tmp_path):
    out = tmp_path / "answer.json"
    out.write_text(json.dumps({"title": "題", "body": "本文\n\n続き",
                               "spoken_reply": "できたよ", "sources": ["a.md"]}), encoding="utf-8")
    result = CodexAgent._parse(out, "note")
    assert result.error is None
    assert (result.title, result.body, result.sources) == ("題", "本文\n\n続き", ["a.md"])


# --- セッション -----------------------------------------------------------

class Recorder:
    """送ったイベントを覚えるだけの端末。"""
    def __init__(self):
        self.sent = []

    async def send_json(self, event):
        self.sent.append(event)


def _session(agent, tmp_path):
    hub = SimpleNamespace(vault_path=tmp_path)
    socket = Recorder()
    session = Session(socket, hub, agent, None, None)
    return session, socket


NOTE = SimpleNamespace(intent="NOTE", mode="note", matched="note", long=True, direct=None)


@_sync
async def test_下書きまで運んで編集URLを返す(tmp_path, monkeypatch):
    class Agent:
        async def run(self, text, mode, timeout=None, use_session=False):
            assert mode == "note"
            # **Vault を書き換える道へ入らないこと**（読み取り専用で走らせる）
            assert use_session is False
            return AgentResult(summary="題", spoken_reply="できたよ", title="題", body="本文")

    written = {}

    async def fake_write(title, body, with_thumbnail=True):
        written.update(title=title, body=body, thumb=with_thumbnail)
        return {"ok": True, "url": "https://editor.note.com/notes/nX/edit/"}

    monkeypatch.setattr(note_writer, "write", fake_write)
    session, socket = _session(Agent(), tmp_path)
    await session._write_note("noteに書いて", NOTE)

    assert written == {"title": "題", "body": "本文", "thumb": False}
    done = [e for e in socket.sent if e["type"] == "agent.completed"]
    assert len(done) == 1
    assert "nX" in done[0]["summary"]
    assert not [e for e in socket.sent if e["type"] == "approval.required"]


@_sync
async def test_サムネも頼んだときだけ生成して渡す(tmp_path, monkeypatch):
    class Agent:
        async def run(self, text, mode, timeout=None, use_session=False):
            return AgentResult(summary="題", spoken_reply="できたよ", title="題", body="本文")

    written = {}

    async def fake_write(title, body, with_thumbnail=True):
        written.update(title=title, body=body, thumb=with_thumbnail)
        return {"ok": True, "url": "https://editor.note.com/notes/nX/edit/"}

    monkeypatch.setattr(note_writer, "write", fake_write)
    session, _ = _session(Agent(), tmp_path)
    await session._write_note("JARVISのnoteの記事を書いて。サムネも作って", NOTE)

    assert written == {"title": "題", "body": "本文", "thumb": True}


@_sync
async def test_下書きに失敗したら成功と言わない(tmp_path, monkeypatch):
    class Agent:
        async def run(self, *a, **k):
            return AgentResult(summary="題", spoken_reply="ok", title="題", body="本文")

    async def fake_write(title, body, with_thumbnail=True):
        return {"ok": False, "error": "no_header_button", "message": "だめだった"}

    monkeypatch.setattr(note_writer, "write", fake_write)
    session, socket = _session(Agent(), tmp_path)
    await session._write_note("noteに書いて", NOTE)

    assert not [e for e in socket.sent if e["type"] == "agent.completed"]
    errors = [e for e in socket.sent if e["type"] == "system.error"]
    assert errors and errors[-1]["code"] == "NO_HEADER_BUTTON"


@_sync
async def test_走っている最中は断る(tmp_path, monkeypatch):
    """2本同時に走らせない。作りかけの記事が note に増えるより待たせる。"""
    class Agent:
        async def run(self, *a, **k):
            raise AssertionError("走っている間はエージェントを起動しない")

    monkeypatch.setattr(note_writer, "busy", lambda: True)
    session, socket = _session(Agent(), tmp_path)
    await session._write_note("noteに書いて", NOTE)

    errors = [e for e in socket.sent if e["type"] == "system.error"]
    assert errors and errors[-1]["code"] == "NOTE_BUSY"
