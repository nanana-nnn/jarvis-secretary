"""繋がっている端末と、そこへ配り続けるイベント（DESIGN.md §12）。

常設端末は1台だけを音声入力元にする。古い PWA タブが残ると同じ手拍子に
複数インスタンスが反応するので、新しい接続が来たら古い方を閉じる。

配色・壁紙は「変わったら知らせる」、テレメトリと3段目は「5秒ごとに配る」。
重い処理（/proc の全走査と git status）は同じ便に乗せて回数を増やさない。
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

from . import wallpapers
from .clock import timestamp_ms
from .facts import read_processes, read_telemetry
from .gitstate import read_vault
from .scheme import read_scheme, scheme_event

logger = logging.getLogger("uvicorn.error")

# 配色・壁紙の見張り間隔（秒）
WATCH_EVERY_S = 1
# テレメトリと3段目を配る間隔（秒）
TELEMETRY_EVERY_S = 5


class Hub:
    def __init__(self, vault_path: Path, scheme_path: Path) -> None:
        self.vault_path = vault_path
        self.scheme_path = scheme_path
        self.clients: set[WebSocket] = set()
        # busy 判定に使う直前の CPU 時間。Hub 単位で持つ（モジュール変数にしない）
        self._cpu_seen: dict[str, tuple[int, float]] = {}

    # --- 接続の出入り -----------------------------------------------------

    async def adopt(self, socket: WebSocket) -> None:
        """この socket を唯一の入力元にする。先にいた端末は閉じる。"""
        for previous in tuple(self.clients):
            if previous is socket:
                continue
            with suppress(RuntimeError, WebSocketDisconnect):
                await previous.close(code=4000, reason="new active client")
            self.clients.discard(previous)
        self.clients.add(socket)

    def release(self, socket: WebSocket) -> None:
        self.clients.discard(socket)

    # --- 配るもの ---------------------------------------------------------

    def scheme_event(self) -> dict[str, object]:
        return scheme_event(self.scheme_path)

    def wallpaper_event(self) -> dict[str, object]:
        source = wallpapers.current_source()
        version = wallpapers.current_version(source)
        # 変換に失敗したら version を空で返す。壁紙なしとして扱わせる
        ready = wallpapers.current_webp(source, version) is not None
        return {"type": "wallpaper.changed", "version": version if ready else "", "ts": timestamp_ms()}

    def telemetry_event(self) -> dict[str, object]:
        return read_telemetry()

    def live_event(self) -> dict[str, object]:
        """3段目に出す「今どうなっているか」。すべて実測。数えられないものは出さない。

        重い処理（/proc の全走査と git status）が入るので、5秒間隔の
        テレメトリと同じ便に乗せて回数を増やさない。
        """
        return {
            "type": "system.live",
            "apps": read_processes(self._cpu_seen),
            "vault": read_vault(self.vault_path),
            "phones": len(self.clients),   # 実際に繋がっている台数。サーバーが持っている
            "ts": timestamp_ms(),
        }

    async def broadcast(self, event: dict[str, object]) -> None:
        for client in tuple(self.clients):
            with suppress(RuntimeError, WebSocketDisconnect):
                await client.send_json(event)

    # --- 常駐ループ -------------------------------------------------------

    async def watch_scheme(self) -> None:
        previous = read_scheme(self.scheme_path)
        previous_paper = wallpapers.current_version(wallpapers.current_source())
        while True:
            scheme = read_scheme(self.scheme_path)
            if scheme != previous:
                previous = scheme
                await self.broadcast(self.scheme_event())

            # 壁紙は配色と同じタイミングで変わる。版が変われば作り直して知らせる
            paper = wallpapers.current_version(wallpapers.current_source())
            if paper != previous_paper:
                previous_paper = paper
                await self.broadcast(self.wallpaper_event())
            await asyncio.sleep(WATCH_EVERY_S)

    async def push_telemetry(self) -> None:
        while True:
            for event in (self.telemetry_event(), self.live_event()):
                await self.broadcast(event)
            await asyncio.sleep(TELEMETRY_EVERY_S)
