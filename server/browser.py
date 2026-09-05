"""作業が見える常駐ブラウザ（2026-09-05、本人の指定）。

常駐ターミナル（server/terminal.py）と同じ扱いで、**ブラウザも開いたままにする。**
「話しかける→PCの画面でブラウザが勝手に動く→結果だけスマホに返る」を見せるのが
目的なので、ヘッドレスにしない。終わってもウィンドウを閉じない。

**普段の Chrome は触らない。** 専用プロファイル（PROFILE_DIR）で開く。
noteのログインはこのプロファイルの中にだけ残るので、失敗しても日常の環境に
影響しない（2026-09-05、本人の選択）。ログインは最初の1回だけ本人が手で行う。

ここに note 固有の知識は持たない（それは server/note_draft.py）。
このモジュールが持つのは「1枚のブラウザを開いたまま保つ」ことだけ。
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import os
from pathlib import Path

logger = logging.getLogger("uvicorn.error")

# 専用プロファイルの置き場。caelestia の scheme.json と同じ ~/.local/state 配下に置く
PROFILE_DIR = Path(
    os.getenv("BROWSER_PROFILE_DIR")
    or Path.home() / ".local/state/jarvis-secretary/browser-profile"
)

# 実体は既に入っている Google Chrome を使う（channel="chrome"）。
# Playwright 同梱の Chromium を落とすと 150MB 増えるうえ、note のような
# 商用サイトは Chrome のほうが素直に動く。プロファイルだけ分ければ
# 「普段の Chrome を触らない」は満たせる
CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")

# 画面に見せるための起動引数。最大化して、自動操作である旨のバーは消さない
# （消すと「本人が操作している」ように見えてしまう。見せるのが目的なので残す）
LAUNCH_ARGS = ("--start-maximized",)


class VisibleBrowser:
    """専用プロファイルのブラウザ1枚。開いたまま保つ。

    `page()` を呼ぶと、開いていなければ開き、使い回すタブを返す。
    **閉じるのは close() を呼んだときだけ。** ジョブが終わっても閉じない。
    """

    def __init__(self, profile_dir: Path | None = None, channel: str | None = None) -> None:
        self.profile_dir = profile_dir or PROFILE_DIR
        self.channel = channel or CHANNEL
        self._playwright = None
        self._context = None
        self._lock = asyncio.Lock()

    def alive(self) -> bool:
        return self._context is not None

    async def context(self):
        """開いていなければ開く。**1枚しか開かない**（terminal と同じ約束）。"""
        async with self._lock:
            if self._context is not None:
                return self._context
            from playwright.async_api import async_playwright

            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                channel=self.channel,
                headless=False,                 # **見せるのが目的**（本人の指定）
                args=list(LAUNCH_ARGS),
                viewport=None,                  # ウィンドウの実寸に従わせる
                locale="ja-JP",
            )
            # ブラウザ側から閉じられたら、次の依頼で開き直せるように忘れる
            self._context.on("close", lambda _: self._forget())
            logger.info("[BROWSER] opened (profile=%s)", self.profile_dir)
            return self._context

    def _forget(self) -> None:
        logger.info("[BROWSER] closed by user")
        self._context = None

    async def page(self):
        """使い回すタブ。既にあるタブの1枚目を使い、無ければ作る。"""
        context = await self.context()
        pages = [page for page in context.pages if not page.is_closed()]
        return pages[0] if pages else await context.new_page()

    async def close(self) -> None:
        with suppress(Exception):
            if self._context is not None:
                await self._context.close()
        with suppress(Exception):
            if self._playwright is not None:
                await self._playwright.stop()
        self._context = None
        self._playwright = None
