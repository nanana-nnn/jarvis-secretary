"""書き起こし（DESIGN.md §8「faster-whisper 設定」）。

仕様は `large-v3` を第一候補としつつ「起動が重い／精度不足なら medium へ落とす」
と書いてある。**この機体では large も medium も実時間比が足りなかったので
`small` を既定にしている。** 実測（12秒の日本語・同一機体）:

    faster-whisper small        2.6s  0.22x  785MB   ← 採用
    faster-whisper medium       7.7s  0.65x  1957MB
    whisper.cpp    small-q5     4.0s  0.34x  493MB
    whisper.cpp    medium-q5   14.3s  1.20x  1142MB  会話にならない
    whisper.cpp    large-v3-turbo-q5 18.9s 1.57x     質は最良だが遅すぎる

whisper.cpp のほうが速いと見込んで測ったが、この CPU では CTranslate2 の
int8 のほうが速かった。数字は `WHISPER_MODEL` で上書きできるので、
肉声で足りなければ medium へ上げる。

モデルの読み込みは重い（初回はダウンロードも走る）。サーバー起動時に一度だけ
読み、以降は常駐させる（§8「起動時に一度だけロードし、常駐させる」）。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os

logger = logging.getLogger("uvicorn.error")

SAMPLE_RATE = 16_000
DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "small")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE", "int8")   # cuda なら float16
LANGUAGE = "ja"                                        # §8「language は "ja" 固定」
BEAM_SIZE = 5


@dataclass
class Transcript:
    text: str
    ms: int          # 書き起こしにかかった時間。実時間比の監視に使う


class Transcriber:
    """faster-whisper の薄い包み。読み込みは遅延させ、失敗しても落ちない。

    音声が来ないうちからモデルを抱えても意味がないので、最初の書き起こしまで
    読み込みを遅らせる。読み込めなかった場合は `ready` が False のままになり、
    呼び出し側は「書き起こせない」と分かる（黙って空文字を返さない）。
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None
        self._error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def error(self) -> str | None:
        return self._error

    def load(self) -> None:
        """同期で読み込む。重いので、呼ぶのは起動時かワーカースレッドから。"""
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_name, device=DEVICE, compute_type=COMPUTE_TYPE)
            self._error = None
            logger.info("[STT] loaded model=%s device=%s compute=%s", self.model_name, DEVICE, COMPUTE_TYPE)
        except Exception as exc:                      # noqa: BLE001 - 何で落ちても起動は続ける
            self._error = f"{type(exc).__name__}: {exc}"
            logger.warning("[STT] load failed: %s", self._error)

    def _run(self, pcm: bytes) -> Transcript:
        import time
        import numpy as np

        started = time.monotonic()
        # Int16 LE → float32 [-1, 1]。faster-whisper は float32 の配列を受け取れる
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(          # type: ignore[union-attr]
            audio, language=LANGUAGE, vad_filter=True, beam_size=BEAM_SIZE,
        )
        text = "".join(segment.text for segment in segments).strip()
        return Transcript(text=text, ms=int((time.monotonic() - started) * 1000))

    async def transcribe(self, pcm: bytes) -> Transcript | None:
        """PCM を書き起こす。読み込めていなければ None（空文字と区別する）。

        推論は CPU を数秒占有するので、必ずスレッドへ出してイベントループを止めない。
        同時に走らせるとメモリを二重に食うので、1本ずつに絞る。
        """
        async with self._lock:
            if self._model is None:
                await asyncio.to_thread(self.load)
            if self._model is None:
                return None
            return await asyncio.to_thread(self._run, pcm)
