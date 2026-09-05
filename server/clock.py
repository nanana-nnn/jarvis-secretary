"""イベントに載せる時刻。

`monotonic_ns` を使う。**壁時計にしない。** 常設端末は寝かせたまま何日も動くので、
NTP の補正やサマータイムで巻き戻ると、経過時間（`took` や `elapsed`）が
負になったり飛んだりする。ここが返すのは「起動からの経過ミリ秒」で、
端末側も差分としてしか使わない。
"""
from __future__ import annotations

from time import monotonic_ns


def timestamp_ms() -> int:
    return monotonic_ns() // 1_000_000
