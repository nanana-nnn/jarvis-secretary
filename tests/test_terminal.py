"""常駐ターミナルの検証（2026-09-04、本人の指定：作業を出しっぱなしで見せる）。

ここで確かめるのは**配管**であって、見た目ではない。
ウィンドウマネージャの無い環境でも回せるよう、`foot` の代わりに
「worker をそのまま bash で走らせる」起動コマンドを差し替えて使う。
そのため画面は出ないが、queue → 実行 → .done → 終了コード という
Python 側が頼っている約束はすべて本物と同じ経路を通る。
"""
import asyncio
from functools import wraps
import json
from pathlib import Path

import pytest

from server.terminal import VisibleTerminal, colour_options


def _sync(test):
    """非同期のテストを普通のテストとして回す（tests/test_briefing.py と同じ理由）。"""
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


# 本物は `foot --title {title} bash {worker}`。ここは端末を開かずに worker だけ回す
HEADLESS_LAUNCH = "bash {worker} >/dev/null 2>&1"


def _terminal(tmp_path: Path) -> VisibleTerminal:
    return VisibleTerminal(launch=HEADLESS_LAUNCH, root=tmp_path / "term")


@_sync
async def test_a_job_runs_and_its_exit_code_comes_back(tmp_path: Path) -> None:
    """終了コードはプロセスの終了ではなく worker が書く .done から取る
    （ターミナルは開いたままなので、プロセスの終了は待てない）。"""
    term = _terminal(tmp_path)
    stdin = tmp_path / "prompt.txt"
    stdin.write_text("ignored\n", encoding="utf-8")
    out = tmp_path / "out.txt"

    code = await term.run(f"cat > {out}", tmp_path, stdin, timeout=20)
    assert code == 0
    assert out.read_text(encoding="utf-8") == "ignored\n", "標準入力が渡っていない"
    term.close()


@_sync
async def test_a_failing_job_reports_its_code(tmp_path: Path) -> None:
    """失敗を 0 と取り違えない（§17 AGENT_FAILED の入口）。"""
    term = _terminal(tmp_path)
    stdin = tmp_path / "prompt.txt"
    stdin.write_text("x", encoding="utf-8")

    assert await term.run("exit 3", tmp_path, stdin, timeout=20) == 3
    term.close()


@_sync
async def test_jobs_run_where_they_are_told_to(tmp_path: Path) -> None:
    """`codex exec resume --last` は --cd を取らず、実際の cwd でどのセッションを
    拾うか決まる。常駐ターミナル経由でも cwd が効いていること（2026-09-04 の実測）。"""
    term = _terminal(tmp_path)
    stdin = tmp_path / "prompt.txt"
    stdin.write_text("x", encoding="utf-8")
    workdir = tmp_path / "vault"
    workdir.mkdir()
    out = tmp_path / "where.txt"

    assert await term.run(f"pwd > {out}", workdir, stdin, timeout=20) == 0
    assert out.read_text(encoding="utf-8").strip() == str(workdir)
    term.close()


@_sync
async def test_a_closed_terminal_is_reopened_for_the_next_job(tmp_path: Path) -> None:
    """間違って閉じられても、次の依頼で開き直す（本人の指定・2026-09-04）。"""
    term = _terminal(tmp_path)
    stdin = tmp_path / "prompt.txt"
    stdin.write_text("x", encoding="utf-8")

    assert await term.run("true", tmp_path, stdin, timeout=20) == 0
    assert term.alive()

    term.close()                    # 本人が × で閉じた状況
    assert not term.alive()

    assert await term.run("true", tmp_path, stdin, timeout=20) == 0, "開き直していない"
    assert term.alive()
    term.close()


@_sync
async def test_a_cancelled_job_does_not_leave_the_work_running(tmp_path: Path) -> None:
    """「やめて」で止めたとき、codex を残さない。

    worker は `setsid` で子を独立したプロセスグループにして pid を書く。
    bash だけ殺すと下の codex が生き残って喋り続けるので、グループごと落とす。
    """
    term = _terminal(tmp_path)
    stdin = tmp_path / "prompt.txt"
    stdin.write_text("x", encoding="utf-8")
    marker = tmp_path / "still-running.txt"

    # 3秒待ってから印を残す仕事。止められていれば印は残らない
    job = term.run(f"sleep 3; touch {marker}", tmp_path, stdin, timeout=20)
    task = asyncio.create_task(job)
    await asyncio.sleep(1.2)        # worker が拾って走り出すまで待つ
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(2.5)        # 止まっていなければ、この間に印が残る
    assert not marker.exists(), "止めたはずの仕事が動き続けている"
    term.close()


@_sync
async def test_it_says_so_when_the_terminal_cannot_be_opened(tmp_path: Path) -> None:
    """ディスプレイが無い等で開けないとき、黙って固まらずに None を返す
    （呼び出し側はこれを AGENT_FAILED として本人へ伝える）。"""
    term = VisibleTerminal(launch="this-command-does-not-exist-{title}-{worker}",
                           root=tmp_path / "term")
    stdin = tmp_path / "prompt.txt"
    stdin.write_text("x", encoding="utf-8")

    # シェル経由なので起動自体は成功し、すぐ非ゼロで終わる。
    # そのまま .done を待つと固まるので、短いタイムアウトで抜けることを見る
    with pytest.raises(asyncio.TimeoutError):
        await term.run("true", tmp_path, stdin, timeout=2)
    term.close()


@_sync
async def test_a_second_terminal_is_not_opened_when_one_is_already_up(tmp_path: Path) -> None:
    """**開いていたら開かない**（本人の指定・2026-09-05）。

    ここで見るのは「同じ VisibleTerminal の2回目」ではなく、
    **サーバーを再起動したとき**。Python 側の記憶は消えるので、別インスタンスが
    前回のウィンドウを見つけられないと2枚目を開いてしまう（実機でそうなった）。
    """
    first = _terminal(tmp_path)
    stdin = tmp_path / "prompt.txt"
    stdin.write_text("x", encoding="utf-8")
    assert await first.run("true", tmp_path, stdin, timeout=20) == 0
    assert first.alive()
    running = first.worker_pid()
    assert running is not None

    # サーバー再起動に相当。同じ場所を見る新しいインスタンス
    restarted = _terminal(tmp_path)
    assert restarted.alive(), "前回のウィンドウを見つけられていない"
    assert await restarted.ensure_running() is True
    assert restarted.worker_pid() == running, "2枚目を開いてしまっている"

    restarted.close()
    assert first.worker_pid() is None


@_sync
async def test_closing_stops_the_worker_loop_too(tmp_path: Path) -> None:
    """起動役だけ殺しても worker ループは生き残る。**そこまで止める。**
    （2026-09-05、テストが残した worker が30個以上溜まっていた）"""
    term = _terminal(tmp_path)
    stdin = tmp_path / "prompt.txt"
    stdin.write_text("x", encoding="utf-8")
    assert await term.run("true", tmp_path, stdin, timeout=20) == 0
    pid = term.worker_pid()
    assert pid is not None

    term.close()
    await asyncio.sleep(0.5)
    assert not Path(f"/proc/{pid}").exists(), "worker が回り続けている"


def test_the_terminal_follows_the_wallpaper_colours(tmp_path: Path) -> None:
    """foot.ini に色が無いので、渡さないと内蔵の暗い既定色になる。
    ライトテーマなのにターミナルだけ黒い、が起きる（2026-09-05 実機で指摘）。"""
    scheme = tmp_path / "scheme.json"
    scheme.write_text(json.dumps({"mode": "light", "colours": {
        "background": "F8F9FE", "onSurface": "2d333a",
        **{f"term{i}": f"{i:02x}00ff" for i in range(16)},
    }}), encoding="utf-8")

    options = colour_options(scheme)
    assert "-o colors.background=f8f9fe" in options, "大文字のまま渡している"
    assert "-o colors.foreground=2d333a" in options
    assert "-o colors.regular0=0000ff" in options    # term0 が通常色の0番
    assert "-o colors.bright0=0800ff" in options     # term8 が明色の0番
    assert "-o colors.regular8=" not in options, "regular は 0〜7 まで"


def test_a_broken_scheme_leaves_the_default_colours(tmp_path: Path) -> None:
    """配色が読めなくてもターミナルは開く。色だけ既定に落ちる。"""
    assert colour_options(tmp_path / "missing.json") == ""

    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert colour_options(broken) == ""

    # 1色だけ壊れていても、残りは渡す（全部捨てて真っ黒に戻さない）
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"colours": {
        "background": "ffffff", "onSurface": "not-a-colour", "term0": "123456",
    }}), encoding="utf-8")
    options = colour_options(partial)
    assert "colors.background=ffffff" in options
    assert "colors.foreground" not in options
    assert "colors.regular0=123456" in options
