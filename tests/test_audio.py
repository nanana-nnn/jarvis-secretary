"""発話切り出しの検証（DESIGN.md §8 / §6 のタイマー定数）。

モデルを読まずに済むよう、切り出しだけを合成音で確かめる。
"""
import math
import struct

from server.audio import (FRAME_BYTES, FRAME_MS, MAX_UTTERANCE_MS, SAMPLE_RATE,
                          SILENCE_MS, SpeechSplitter)


def tone(ms: int, hz: int = 220) -> bytes:
    """webrtcvad が「声」と判定しやすい、倍音のある有声音に近い波。"""
    frames = SAMPLE_RATE * ms // 1000
    out = bytearray()
    for i in range(frames):
        t = i / SAMPLE_RATE
        value = (math.sin(2 * math.pi * hz * t) * 0.5
                 + math.sin(2 * math.pi * hz * 2 * t) * 0.3
                 + math.sin(2 * math.pi * hz * 3 * t) * 0.2)
        out += struct.pack("<h", int(value * 12000))
    return bytes(out)


def silence(ms: int) -> bytes:
    return b"\x00\x00" * (SAMPLE_RATE * ms // 1000)


def test_frame_size_matches_webrtcvad_requirement() -> None:
    """webrtcvad は 10/20/30ms しか受け付けない。ここがずれると全部落ちる。"""
    assert FRAME_MS in (10, 20, 30)
    assert FRAME_BYTES == SAMPLE_RATE * 2 * FRAME_MS // 1000


def test_silence_alone_never_produces_an_utterance() -> None:
    splitter = SpeechSplitter()
    assert splitter.feed(silence(3_000)) == []
    assert not splitter.speaking


def test_utterance_ends_after_the_specified_silence() -> None:
    """§6 VAD_SILENCE_MS = 1200。無音がそれだけ続いたら終端する。

    実時間は 1200ms ちょうどにはならない。VAD は無音へ移る境目の数フレームを
    まだ声と判定するので、そのぶん後ろへずれる。仕様が言っているのは
    「規定より早く切らない」ことなので、そこを見る。
    """
    splitter = SpeechSplitter()
    assert splitter.feed(tone(600)) == [], "話している間は確定しない"

    fed = 0
    done: list = []
    while not done and fed < SILENCE_MS * 3:
        done.extend(splitter.feed(silence(100)))
        fed += 100

    assert done, "無音を足しても終端しない"
    assert fed >= SILENCE_MS, f"規定({SILENCE_MS}ms)より早く切れている: {fed}ms"
    assert fed <= SILENCE_MS * 2, f"終端が遅すぎる: {fed}ms"
    assert done[0].reason == "silence"
    assert done[0].ms > 0
    assert len(done[0].pcm) == done[0].ms * SAMPLE_RATE * 2 // 1000


def test_trailing_silence_is_not_sent_to_transcription() -> None:
    """終端の無音は落とす。渡しても意味がなく、書き起こしの時間だけ食う。"""
    splitter = SpeechSplitter()
    splitter.feed(tone(800))
    done = splitter.feed(silence(SILENCE_MS + 200))
    assert done and done[0].ms < 800 + SILENCE_MS


def test_long_speech_is_cut_at_the_limit() -> None:
    """§6 UTTERANCE_MAX_MS = 30000。話し続けても必ず切れて先へ進む。"""
    splitter = SpeechSplitter()
    done: list = []
    for _ in range(40):                       # 40秒ぶん流し込む
        done.extend(splitter.feed(tone(1_000)))
        if done:
            break
    assert done, "上限で切れずに溜め続けている"
    assert done[0].reason == "max-length"
    assert done[0].ms <= MAX_UTTERANCE_MS + FRAME_MS


def test_chunks_may_be_split_anywhere() -> None:
    """iPhone は 20ms 単位で送るが、VAD は 30ms 単位。端数をまたいでも壊れない。"""
    whole = SpeechSplitter()
    expected = whole.feed(tone(700) + silence(SILENCE_MS + 200))

    piecewise = SpeechSplitter()
    data = tone(700) + silence(SILENCE_MS + 200)
    got: list = []
    for i in range(0, len(data), 640):        # 20ms = 640バイト
        got.extend(piecewise.feed(data[i:i + 640]))

    assert len(got) == len(expected) == 1
    assert got[0].ms == expected[0].ms, "切り方で結果が変わってはいけない"


def test_flush_returns_speech_in_progress() -> None:
    """接続が切れたとき、話しかけの内容を捨てない。"""
    splitter = SpeechSplitter()
    splitter.feed(tone(500))
    left = splitter.flush()
    assert left is not None and left.reason == "disconnect"
    assert splitter.flush() is None, "二度目は何も残っていない"
