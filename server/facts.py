"""PC の実測値（3段目のテレメトリ）。

**数えられないものは出さない。** 読めなかった項目は 0 や "?" のまま返し、
それらしい値を作らない。fastfetch と数が合うことを合格条件にしている項目
（packages / mem / uptime）は、合わせ方の根拠を各関数の docstring に置く。
"""
from __future__ import annotations

from contextlib import suppress
from functools import lru_cache
import os
from pathlib import Path
import platform
import pwd
import socket as system_socket
from time import monotonic_ns

from .clock import timestamp_ms


def format_uptime(seconds: float) -> str:
    """fastfetch と同じ「9 hours, 55 minutes」表記。0 の単位は出さない。"""
    total = int(seconds)
    parts = []
    for count, unit in ((total // 86400, "day"), (total % 86400 // 3600, "hour"), (total % 3600 // 60, "minute")):
        if count:
            parts.append(f"{count} {unit}{'s' if count != 1 else ''}")
    return ", ".join(parts) or "less than a minute"


@lru_cache(maxsize=1)
def static_facts() -> dict[str, str]:
    """再起動するまで変わらない項目。毎回読み直さない。"""
    facts = {"kernel": platform.release(), "hname": system_socket.gethostname(), "shell": "?", "user": "?", "distro": "?"}
    try:
        entry = pwd.getpwuid(os.getuid())
        facts["user"] = entry.pw_name
        # $SHELL は起動元（Claude Code なら zsh）を指すので passwd のログインシェルを見る
        facts["shell"] = Path(entry.pw_shell).name
    except (KeyError, OSError):
        pass
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                facts["distro"] = line.split("=", 1)[1].strip().strip('"')
                break
    except OSError:
        pass
    return facts


def read_packages() -> int:
    """fastfetch の packages {all} と同じ数。

    pacman だけだと合わない。fastfetch は ~/Applications の AppImage も数えるので、
    実機では pacman 1490 + appimage 2 = 1492 になる（`fastfetch --structure packages`
    で確認）。pacman の数は `pacman -Q | wc -l` と一致する。
    """
    total = 0
    try:
        total += sum(1 for entry in Path("/var/lib/pacman/local").iterdir() if entry.is_dir())
    except OSError:
        pass
    try:
        total += sum(1 for entry in (Path.home() / "Applications").iterdir()
                     if entry.is_file() and entry.suffix.lower() == ".appimage")
    except OSError:
        pass
    return total


# 3段目に出す「生きているもの」。名前は /proc/<pid>/comm と cmdline の両方で見る
# （electron 系は comm が "obsidian" にならないことがあるため）。
# ここに嘘を混ぜない。検出できないものは足さないこと。
WATCHED = (
    ("obsidian", ("obsidian",)),
    ("codex", ("codex",)),
    ("claude", ("claude",)),
    ("chrome", ("chrome", "chromium")),
    ("term", ("foot", "kitty", "alacritty")),
)


def read_processes(seen: dict[str, tuple[int, float]]) -> dict[str, dict[str, object]]:
    """監視対象ごとに、動いているか（alive）と処理中か（busy）を返す。

    busy は CPU 時間の増え方で見る。前回の観測との差分が要るので、
    最初の1回は必ず False になる（起動直後に「処理中」と嘘をつかないため）。

    `seen` は呼び出し側が持つ。モジュール変数にすると別インスタンスへ状態が
    漏れて「初回は False」が保証できなくなる（テストで実際に破れた）。
    """
    ticks = os.sysconf("SC_CLK_TCK")
    now = monotonic_ns() / 1e9
    totals = {name: 0 for name, _ in WATCHED}
    found = {name: False for name, _ in WATCHED}

    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip().lower()
            cmdline = (entry / "cmdline").read_bytes().decode("utf-8", "ignore").replace("\0", " ").lower()
            stat = (entry / "stat").read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        haystack = f"{comm} {cmdline}"
        for name, needles in WATCHED:
            if not any(n in haystack for n in needles):
                continue
            found[name] = True
            # stat は comm に空白を含みうるので、必ず最後の ')' より後ろを読む
            fields = stat[stat.rfind(")") + 2:].split()
            with suppress(IndexError, ValueError):
                totals[name] += int(fields[11]) + int(fields[12])  # utime + stime

    result: dict[str, dict[str, object]] = {}
    for name, _ in WATCHED:
        busy = False
        previous = seen.get(name)
        if previous is not None:
            elapsed = now - previous[1]
            if elapsed > 0:
                # 1コアの5%以上を使っていたら「処理中」とみなす
                busy = (totals[name] - previous[0]) / ticks / elapsed > 0.05
        seen[name] = (totals[name], now)
        result[name] = {"alive": found[name], "busy": busy and found[name]}
    return result


def read_telemetry() -> dict[str, object]:
    used_ratio, used_gib, total_gib, uptime_seconds = 0.0, 0.0, 0.0, 0.0
    try:
        memory = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0])
        # fastfetch と同じ「total - available」を使用量とする（used+buff/cache ではない）
        total_kib, available_kib = memory["MemTotal"], memory["MemAvailable"]
        used_ratio = 100 * (1 - available_kib / total_kib)
        used_gib, total_gib = (total_kib - available_kib) / 1048576, total_kib / 1048576
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        pass
    return {
        "type": "system.telemetry",
        "load": round(os.getloadavg()[0], 2),
        "memory": round(used_ratio, 1),
        "uptime": format_uptime(uptime_seconds),
        "mem": f"{used_gib:.2f} GiB / {total_gib:.2f} GiB",
        "pkgs": read_packages(),
        **static_facts(),
        "host": system_socket.gethostname(),
        "ts": timestamp_ms(),
    }
