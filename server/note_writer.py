"""声で頼まれた note の下書きを作る（2026-09-05）。

`note_draft.py` は「与えられた題と本文を入れる」だけの部品で、CLI から叩く前提
だった。ここはそれを JARVIS 本体から呼ぶための層で、次の3つを受け持つ。

1. ブラウザを**1枚だけ常駐で持つ**（DESIGN.md §18.1「開いたままにする」）。
   専用プロファイルは1プロセスしか掴めないので、毎回開き直さない
2. 見出し画像を題から作る（`thumbnail.py`）。作れなければ画像なしで進む
3. **公開に触れない。** 下書き保存までで、失敗しても作り直さない

同時に2本走らせない。走っている間に次を頼まれたら断る（作りかけの記事が
note に増えるより、待ってもらうほうがよい）。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import tempfile

from . import thumbnail
from .browser import VisibleBrowser
from .note_draft import create_draft

logger = logging.getLogger("uvicorn.error")

_lock = asyncio.Lock()
_browser: VisibleBrowser | None = None


async def _shared_browser() -> VisibleBrowser:
    """常駐の1枚を返す。**閉じない**（見えていることが要件）。"""
    global _browser
    if _browser is None:
        _browser = VisibleBrowser(layout="full")
    return _browser


async def close() -> None:
    """後片付け。サーバーを止めるときだけ呼ぶ。"""
    global _browser
    if _browser is not None:
        await _browser.close()
        _browser = None


def busy() -> bool:
    return _lock.locked()


async def write(title: str, body: str, with_thumbnail: bool = True) -> dict:
    """題と本文から下書きを1本作る。返すのは `create_draft` の結果。

    **成否をそのまま返す。** 失敗しても作り直さない（同じ編集URLを見てもらう）。
    """
    if busy():
        return {"ok": False, "error": "note_busy",
                "message": "いま別の下書きを作ってる。終わってからもう一度言って"}
    async with _lock:
        image: Path | None = None
        work = Path(tempfile.mkdtemp(prefix="jarvis-note-"))
        try:
            if with_thumbnail:
                image = thumbnail.make(title, work / "header.png")
                if image is None:
                    # 画像が作れないことは下書きを止める理由にならない。
                    # あとから `note_draft header` で足せる
                    logger.warning("[NOTE] thumbnail could not be made; going without one")
            browser = await _shared_browser()
            result = await create_draft(browser, title, body,
                                        header_image=str(image) if image else None)
            logger.info("[NOTE] %s %s", "ok" if result.get("ok") else result.get("error"),
                        result.get("url", ""))
            return result
        finally:
            # 画像は note へ渡し終えたら要らない（下書きに載っている）
            import shutil
            shutil.rmtree(work, ignore_errors=True)
