"""caelestia が出している配色を読む（DESIGN.md §15）。

壁紙から作り直された `scheme.json` を読んで、iPhone 側の CSS 変数へ配る。
**欠けている色を推測で埋めない。** Material トークンが1つでも欠けたら
配色ごと無効（None）にして、端末には前の配色を使わせる。
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .clock import timestamp_ms

DEFAULT_SCHEME_PATH = Path.home() / ".local/state/caelestia/scheme.json"
HEX_COLOUR = re.compile(r"^[0-9a-fA-F]{6}$")
SCHEME_KEYS = (
    "background",
    "surfaceContainer",
    "surfaceContainerHigh",
    "onSurface",
    "onSurfaceVariant",
    "outlineVariant",
    "primary",
    "onPrimary",
    "error",
)
# 端末のANSI色（caelestia の scheme.json が壁紙から作る term0〜term15）。
# 文字回答カードのプロンプト行は starship.toml と同じ配色にするので、
# Material トークンではなくこちらを使う（2026-09-02、本人の指定
# 「実際のターミナルと同じように」）。使うのは starship が指定している5色。
#   term0=black / term3=yellow / term6=cyan / term7=white / term12=bright-blue
# **任意扱いにする。** 揃っていなくても Material 側の配色は配れるようにして、
# 端末色が無い環境で画面全体が無色に落ちないようにする
TERM_KEYS = ("term0", "term3", "term6", "term7", "term12")


def read_primary(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["colours"]["primary"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return f"#{value.lower()}" if isinstance(value, str) and HEX_COLOUR.fullmatch(value) else None


def read_scheme(path: Path) -> dict[str, str] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        colours = payload["colours"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None

    mode = payload.get("mode")
    if mode not in {"light", "dark"}:
        return None

    scheme = {"mode": mode}
    for key in SCHEME_KEYS:
        value = colours.get(key)
        if not isinstance(value, str) or not HEX_COLOUR.fullmatch(value):
            return None
        scheme[key] = f"#{value.lower()}"
    # 端末色は任意。欠けていても Material 側は配る（画面が無色に落ちないように）
    for key in TERM_KEYS:
        value = colours.get(key)
        if isinstance(value, str) and HEX_COLOUR.fullmatch(value):
            scheme[key] = f"#{value.lower()}"
    return scheme


def scheme_event(path: Path) -> dict[str, object]:
    return {"type": "scheme.changed", "scheme": read_scheme(path), "ts": timestamp_ms()}
