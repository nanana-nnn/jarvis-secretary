"""発話切り出しの検証（DESIGN.md §8 / §6 のタイマー定数）。

モデルを読まずに済むよう、切り出しだけを合成音で確かめる。
"""
import math
import struct

import random

from server.audio import (FRAME_BYTES, FRAME_MS, MAX_UTTERANCE_MS, MIN_UTTERANCE_MS,
                          NOISE_UTTERANCE_MS, QUIET_NOISE_RMS, SAMPLE_RATE, SILENCE_MS,
                          SILENCE_MS_QUIET, SpeechSplitter, frame_rms, silence_target_ms)


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


def room_noise(ms: int, amp: int = 1500, rng: random.Random | None = None) -> bytes:
    """webrtcvad が声と判定しない雑音。**実測で選んだ振幅**（白色 1500 で 0/10 判定）。

    ファンや遠くのテレビのように「無音ではないが声でもない」音を作る。
    種を固定して、判定が走るたびに変わらないようにする。
    **最初の3フレームは webrtcvad が声と判定する**（内部の雑音推定が追いつくまで）。
    暗騒音を上げたいときは、それを通り越すだけの長さを流すこと（実測）。

    **切れ目なく流すときは `rng` を持ち回すこと。** 呼ぶたびに種を作り直すと同じ波形が
    繰り返され、その継ぎ目を webrtcvad が周期的に声と判定して無音が積み上がらない。
    """
    rng = rng or random.Random(7)
    return b"".join(struct.pack("<h", rng.randint(-amp, amp))
                    for _ in range(SAMPLE_RATE * ms // 1000))


def test_frame_size_matches_webrtcvad_requirement() -> None:
    """webrtcvad は 10/20/30ms しか受け付けない。ここがずれると全部落ちる。"""
    assert FRAME_MS in (10, 20, 30)
    assert FRAME_BYTES == SAMPLE_RATE * 2 * FRAME_MS // 1000


def test_silence_alone_never_produces_an_utterance() -> None:
    splitter = SpeechSplitter()
    assert splitter.feed(silence(3_000)) == []
    assert not splitter.speaking


def test_utterance_ends_after_the_specified_silence() -> None:
    """静かな部屋では SILENCE_MS_QUIET（700ms）で終端する（§6、2026-09-08）。

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
    assert splitter.silence_target == SILENCE_MS_QUIET, "無音だけの部屋は静かと判定する"
    assert fed >= SILENCE_MS_QUIET, f"規定({SILENCE_MS_QUIET}ms)より早く切れている: {fed}ms"
    assert fed <= SILENCE_MS_QUIET * 2, f"終端が遅すぎる: {fed}ms"
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


def test_short_noise_is_not_an_utterance() -> None:
    """指パッチンのような一瞬の音を書き起こしへ渡さない。

    実機で 90ms の断片が書き起こしにかかり、空文字が返っていた
    （2026-08-31 のログ）。空振りのぶん待たされるので手前で捨てる。
    """
    splitter = SpeechSplitter()
    splitter.feed(tone(80))                       # 指パッチン相当の一瞬
    done: list = []
    fed = 0
    while fed < SILENCE_MS * 2:
        done.extend(splitter.feed(silence(100)))
        fed += 100
    assert done == [], "一瞬の物音が発話として出ている"


def test_short_reply_still_gets_through() -> None:
    """「はい」程度の短い返事は消さない。下限を上げすぎない歯止め。"""
    splitter = SpeechSplitter()
    splitter.feed(tone(400))
    done: list = []
    fed = 0
    while not done and fed < SILENCE_MS * 3:
        done.extend(splitter.feed(silence(100)))
        fed += 100
    assert done, "短い返事まで捨てている"
    assert done[0].ms >= MIN_UTTERANCE_MS


def test_the_noise_gate_covers_the_clap_residue_measured_in_the_field() -> None:
    """拍手の残響は VAD を通り抜けて発話として確定する（実機で 360ms）。

    それ自体は止められないので、書き起こしが空だったときに
    「物音」として黙って捨てる二段目の関門を app.py が持っている。
    ここではその境界が、実測値をまたいで正しい側にあることを見る。
    上げすぎると、本当に聞き取れなかったときの「聞き取れませんでした」まで
    黙ってしまうので、両側から挟んでおく。
    """
    CLAP_RESIDUE_MS = 360      # 2026-09-04 実機のログ
    assert MIN_UTTERANCE_MS < CLAP_RESIDUE_MS, "残響は VAD の下限では止まらない"
    assert CLAP_RESIDUE_MS <= NOISE_UTTERANCE_MS, "残響が物音として捨てられない"
    assert NOISE_UTTERANCE_MS < 1_000, "上げすぎ。本当の空振りまで黙ってしまう"


def test_silence_target_is_chosen_by_the_noise_floor() -> None:
    """終端の長さは暗騒音で決める。境目は QUIET_NOISE_RMS。"""
    assert silence_target_ms(0.0) == SILENCE_MS_QUIET
    assert silence_target_ms(QUIET_NOISE_RMS) == SILENCE_MS_QUIET
    assert silence_target_ms(QUIET_NOISE_RMS + 1) == SILENCE_MS


def test_room_noise_is_not_speech_but_raises_the_floor() -> None:
    """検証に使う雑音の前提。声と判定されず、静かの境目より大きいこと。"""
    frame = room_noise(FRAME_MS)
    assert frame_rms(frame) > QUIET_NOISE_RMS
    splitter = SpeechSplitter()
    assert splitter.feed(room_noise(2_000)) == [], "雑音だけで発話にしない"
    assert splitter.noise_rms > QUIET_NOISE_RMS, "暗騒音が上がっていない"


def test_noisy_room_keeps_the_long_window() -> None:
    """うるさい部屋では 1200ms のまま。短いほうで切ると文の途中で切れる。

    終端の無音には**デジタルの無音を使う**。実測（2026-09-08）では、直前に大きい音が
    あると webrtcvad はそのあとの白色雑音を声と判定し続け、雑音を流し続けても終端しない
    （振幅 450〜1500 のいずれでも終端せず）。ここで見たいのは「暗騒音で選んだ長さが
    効いているか」なので、判定が安定する無音で確かめる。
    """
    rng = random.Random(7)
    splitter = SpeechSplitter()
    splitter.feed(room_noise(2_000, rng=rng))      # 先に部屋の音を聞かせる
    assert splitter.noise_rms > QUIET_NOISE_RMS
    assert splitter.feed(tone(600)) == []
    assert splitter.silence_target == SILENCE_MS, "うるさい部屋を静かと判定した"

    fed = 0
    done: list = []
    while not done and fed < SILENCE_MS * 3:
        done.extend(splitter.feed(silence(100)))
        fed += 100

    assert done, "無音を足しても終端しない"
    assert fed >= SILENCE_MS, f"静かな部屋の長さで切れている: {fed}ms"


def test_noise_floor_survives_an_utterance() -> None:
    """部屋は発話1回で変わらない。reset で暗騒音まで捨てない。"""
    splitter = SpeechSplitter()
    splitter.feed(room_noise(2_000))
    floor = splitter.noise_rms
    splitter.feed(tone(600))
    splitter.feed(room_noise(SILENCE_MS + 300))
    assert splitter.noise_rms >= floor * 0.5, "発話のたびに暗騒音を測り直している"
