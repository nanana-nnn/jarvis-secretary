"""Vault の git の状態を読む（DESIGN.md §11-1）。

読み取り専用。**ここから git を書き換えるコードを足さない**
（§2-4「commit は自動化しない」）。

「数えられなかった」と「変更が無い」を必ず別の値で返す。同じ値にすると、
警告を出すべき場面で黙ることになる。
"""
from __future__ import annotations

from pathlib import Path
import subprocess


def read_vault(vault: Path) -> dict[str, object]:
    """Vault が git 管理下にあるか、未コミットが何件あるか。数えられなければ触れない。"""
    head = vault / ".git"
    if not head.exists():
        return {"tracked": False, "dirty": 0}
    dirty = 0
    try:
        # git を呼ばずに済ませたいが、状態の正確さは git にしか出せない
        out = subprocess.run(["git", "-C", str(vault), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=5)
        dirty = len([line for line in out.stdout.splitlines() if line.strip()])
    except (OSError, subprocess.SubprocessError):
        return {"tracked": True, "dirty": -1}  # 数えられなかった。0 と偽らない
    return {"tracked": True, "dirty": dirty}


def dirty_paths(vault: Path) -> set[str] | None:
    """§11-1 実行前の `git status --porcelain`。ユーザーの既存変更を識別するために使う。

    数えられなかったときは空集合ではなく None を返す。「dirty が無い」と
    「調べられなかった」を同じ値にすると、警告を出すべき場面で黙ってしまう。
    -z なので core.quotepath による引用が入らず、日本語パスもそのまま取れる。
    """
    if not (vault / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(vault), "status", "--porcelain=v1", "-z"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    entries = out.stdout.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.add(entry[3:])
        # R/C は「移動元」が次のエントリに続く。両方ユーザーの変更として数える
        if entry[0] in ("R", "C"):
            if index < len(entries) and entries[index]:
                paths.add(entries[index])
            index += 1
    return paths
