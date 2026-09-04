"""作業が見える常駐ターミナル（2026-09-04、本人の指定）。

「話しかける→PC画面で勝手に作業する様子が見える→結果だけスマホに返る」。
SNSに出すのが目的なので、**ターミナルは出しっぱなしにする。**

依頼のたびにウィンドウを開いて閉じる方式は 2026-09-04 に一度入れたが、
終わると消えるので「何が起きているか」が残らなかった。ここでは1枚だけ常駐させ、
その中の worker がジョブを順に実行する。画面には過去の実行も残る。

**Python 側はプロセスの終了を待てない**（ターミナルは開いたままなので終了しない）。
代わりに worker が書く `.done`（終了コード）を待つ。止めるときは worker が
書いた `.pid` を使い、プロセスグループごと落とす（codex は子を持つので、
bash だけ殺しても codex が残る）。

ここに codex 固有の知識は無い。渡されたコマンドをそのまま実行するだけなので、
`.env` でバックエンドを差し替えても影響しない（DESIGN.md §2）。
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
import re
import os
import shlex
import signal
import tempfile
from pathlib import Path

logger = logging.getLogger("uvicorn.error")

HEX6 = re.compile(r"^[0-9a-fA-F]{6}$")

# worker がジョブを拾いにいく間隔。人が話しかける間隔に対して十分細かい
POLL_S = 0.1

# 常駐ターミナルの起動。{worker} には下の worker スクリプトのパスが入る。
# foot はシェルではないので、worker を bash に渡す。
# {colours} には配色の -o 指定が入る（下の colour_options）
DEFAULT_LAUNCH = "foot --title {title} {colours} bash {worker}"

WORKER_TITLE = "JARVIS"

# caelestia が壁紙から作る配色。**`~/.config/foot/foot.ini` には色が無い**ので
# （[colors-dark] に alpha と blur しか書かれていない）、渡さないと foot 内蔵の
# 暗い既定色のままになる。ライトテーマなのにターミナルだけ黒い、という
# 食い違いが起きる（2026-09-05、実機で指摘された）。
# caelestia 自身のパネルも alpha しか渡していないので、ここは真似ではなく足す。
# foot は `-o colors.regular0=RRGGBB` の形（# は付けない）で受ける
SCHEME_PATH = Path.home() / ".local/state/caelestia/scheme.json"


def colour_options(scheme_path: Path | None = None) -> str:
    """配色を foot の -o 指定へ組み立てる。読めなければ空文字（既定色のまま）。

    **開いたあとの色は変わらない。** foot は起動時の指定を持ち続けるので、
    壁紙を変えたぶんは次にターミナルを開き直したときから反映される。
    """
    path = scheme_path or SCHEME_PATH
    try:
        colours = json.loads(path.read_text(encoding="utf-8"))["colours"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return ""

    def hex6(key: str) -> str | None:
        value = colours.get(key)
        return value.lower() if isinstance(value, str) and HEX6.fullmatch(value) else None

    options: list[str] = []
    background, foreground = hex6("background"), hex6("onSurface")
    if background:
        options.append(f"colors.background={background}")
    if foreground:
        options.append(f"colors.foreground={foreground}")
    # term0〜7 が通常色、term8〜15 が明色。欠けていたらその色だけ既定に任せる
    for index in range(16):
        value = hex6(f"term{index}")
        if value:
            slot = f"regular{index}" if index < 8 else f"bright{index - 8}"
            options.append(f"colors.{slot}={value}")
    return " ".join(f"-o {shlex.quote(option)}" for option in options)

# ターミナルの中で回り続ける worker。
#   - ジョブ（*.sh）を古い順に1つずつ実行する（§10「同時実行は1ジョブ」）
#   - setsid で自分のプロセスグループを作り、pid を書く（止めるときに使う）
#   - 終了コードを .done に書く。Python 側はこれを待つ
# 画面に残す出力は最小限にする。codex 自身の出力が主役なので、区切りだけ入れる
WORKER_SCRIPT = r"""#!/usr/bin/env bash
queue="$1"
pidfile="$2"
# **自分の PID を残す。** サーバーを再起動すると Python 側の記憶は消えるので、
# 「もう1枚開いているか」はこのファイルでしか分からない。
# 消し忘れると次の起動でもう1枚開いてしまう（2026-09-05、実機で2枚になった）
echo $$ > "$pidfile"
trap 'rm -f "$pidfile"' EXIT
printf '\033]0;%s\007' "JARVIS"
echo "JARVIS worker ready — 依頼を待っています"
echo "（このウィンドウは開いたままにしておいてください）"
while true; do
  job=""
  for candidate in "$queue"/*.sh; do
    [ -e "$candidate" ] || continue
    job="$candidate"
    break
  done
  if [ -z "$job" ]; then
    sleep 0.1
    continue
  fi
  base="${job%.sh}"
  mv "$job" "$base.running" 2>/dev/null || continue
  echo
  echo "──────────────────────────────────────── $(date '+%H:%M:%S')"
  setsid bash "$base.running" &
  child=$!
  echo "$child" > "$base.pid"
  wait "$child"
  code=$?
  rm -f "$base.pid"
  echo "$code" > "$base.done"
  rm -f "$base.running"
done
"""


class VisibleTerminal:
    """常駐ターミナル1枚と、そこへ流すジョブ待ち行列。"""

    def __init__(self, launch: str | None = None, root: Path | None = None) -> None:
        self.launch = launch or os.getenv("AGENT_TERMINAL_CMD") or DEFAULT_LAUNCH
        self.root = root or Path(tempfile.gettempdir()) / "jarvis-terminal"
        self.queue = self.root / "queue"
        self.queue.mkdir(parents=True, exist_ok=True)
        self._worker_file = self.root / "worker.sh"
        self._pid_file = self.root / "worker.pid"
        self._process: asyncio.subprocess.Process | None = None
        self._serial = 0

    def worker_pid(self) -> int | None:
        """今この queue を見ている worker の PID。**別プロセスが開けたものも拾う。**

        Python 側の記憶（_process）だけを見ると、サーバーを再起動したときに
        「前回開いたウィンドウ」が見えず、もう1枚開いてしまう
        （2026-09-05、実機で2枚になった）。PID は使い回されるので、
        cmdline に自分の worker.sh が入っていることまで確かめる。
        """
        try:
            pid = int(self._pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "ignore")
        except OSError:
            return None                      # もう居ない（消し忘れの pid ファイル）
        return pid if str(self._worker_file) in cmdline else None

    def alive(self) -> bool:
        """1枚でも開いていれば True。**開いていたら開かない**（本人の指定）。"""
        if self._process is not None and self._process.returncode is None:
            return True
        return self.worker_pid() is not None

    async def ensure_running(self) -> bool:
        """開いていなければ開く。**閉じられていたらここで開き直す**
        （本人の指定：間違って消したら次の依頼で立ち上げ直す）。"""
        if self.alive():
            return True
        self._worker_file.write_text(WORKER_SCRIPT, encoding="utf-8")
        command = self.launch.format(
            title=shlex.quote(WORKER_TITLE),
            colours=colour_options(),
            worker=(f"{shlex.quote(str(self._worker_file))} "
                    f"{shlex.quote(str(self.queue))} {shlex.quote(str(self._pid_file))}"),
        )
        try:
            self._process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.warning("[TERM] could not open (%s)", exc)
            self._process = None
            return False
        logger.info("[TERM] opened")
        # worker が最初のジョブを拾えるようになるまでの間。ここで待たないと、
        # 開いた直後の1件が queue に置かれたまま少しのあいだ動かないように見える
        await asyncio.sleep(0.4)
        return True

    async def run(self, command: str, cwd: Path, stdin_file: Path, timeout: int) -> int | None:
        """ターミナルの中で実行し、終了コードを返す。開けなければ None。

        ここでは stdout/stderr を捕まえない（画面へ出るのが目的なので）。
        答えは呼び出し側が {out_file} から読む。
        """
        if not await self.ensure_running():
            return None

        self._serial += 1
        base = self.queue / f"job-{self._serial:04d}"
        done, pid_file = base.with_suffix(".done"), base.with_suffix(".pid")
        # cd はジョブ側で行う。`codex exec resume --last` は --cd を取らず、
        # どのセッションを拾うかは実際の cwd で決まる（2026-09-04 の実測）
        base.with_suffix(".sh").write_text(
            f"cd {shlex.quote(str(cwd))}\n{command} < {shlex.quote(str(stdin_file))}\n",
            encoding="utf-8",
        )
        try:
            return await asyncio.wait_for(self._wait(done), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._kill(pid_file)
            raise
        finally:
            for path in (base.with_suffix(".sh"), base.with_suffix(".running"), done, pid_file):
                try: path.unlink()
                except OSError: pass

    async def _wait(self, done: Path) -> int:
        while True:
            try:
                return int(done.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                await asyncio.sleep(POLL_S)

    @staticmethod
    def _kill(pid_file: Path) -> None:
        """走っているジョブを止める。**プロセスグループごと落とす。**
        bash だけ殺すと、その下の codex が残って喋り続ける"""
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def close(self) -> None:
        """ウィンドウと worker を止める。

        **worker まで落とすこと。** 起動役（シェル）だけ終わらせても、その下の
        worker ループは生き残って回り続ける（2026-09-05、テストが残した
        worker が30個以上溜まっていた）。
        """
        pid = self.worker_pid()
        if pid is not None:
            with suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGTERM)
            with suppress(OSError):
                self._pid_file.unlink()
        if self._process is not None and self._process.returncode is None:
            with suppress(ProcessLookupError):
                self._process.terminate()
        self._process = None
