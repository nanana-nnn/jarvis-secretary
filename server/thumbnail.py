"""note の見出し画像を題から作る（2026-09-05）。

**写真も生成AIも使わない。** 文字と面だけで作る。理由は2つ。
出所を説明できない画像を記事に載せないこと（[[自動操作は公開に触れない]] と
同じ考え方）と、magick だけで完結して外部サービスに題を送らずに済むこと。

推奨サイズは note のUIに書かれている 1280×670（＝1.91:1）。
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap

WIDTH, HEIGHT = 1280, 670
# 生成りと紺。JARVISの記録シリーズの見た目を揃える
BACKGROUND = "#F4EFE6"
INK = "#14324F"
ACCENT = "#2E6FA7"
MUTED = "#8A9BA8"
FONT = "Noto-Sans-CJK-JP"
# 1行の文字数。これを超えたら折る。日本語の全角前提
WRAP = 11
MAX_LINES = 3
FOOTER = "JARVIS — 作っている途中の記録"


def _lines(title: str) -> list[str]:
    """題を見出しの行へ折る。**入り切らない分は切る**（潰れた字を出さない）。"""
    wrapped = textwrap.wrap(title, width=WRAP) or [title]
    return wrapped[:MAX_LINES]


def make(title: str, out_path: Path, subtitle: str = "") -> Path | None:
    """題から見出し画像を作る。作れなければ None（画像なしで下書きへ進む）。"""
    lines = _lines(title)
    if not lines:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 行数で本文の開始位置を変える。少ない行を上に寄せない
    top = {1: 300, 2: 250, 3: 200}[len(lines)]
    command = [
        "magick", "-size", f"{WIDTH}x{HEIGHT}", f"xc:{BACKGROUND}",
        "-fill", INK, "-draw", f"rectangle 0,0 {WIDTH},12",
        "-font", FONT,
    ]
    for index, line in enumerate(lines):
        command += ["-fill", INK, "-pointsize", "70",
                    "-annotate", f"+80+{top + index * 95}", line]
    if subtitle:
        command += ["-fill", ACCENT, "-pointsize", "32",
                    "-annotate", f"+80+{top + len(lines) * 95 + 40}", subtitle[:28]]
    command += ["-fill", MUTED, "-pointsize", "26", "-annotate", "+80+590", FOOTER,
                str(out_path)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out_path if out_path.is_file() else None
