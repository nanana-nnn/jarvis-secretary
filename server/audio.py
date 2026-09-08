"""発話の切り出し（DESIGN.md §8 PC側）。

iPhone から 20ms ごとに届く 16kHz mono Int16 LE の生 PCM を受け、
`webrtcvad` で発話区間を判定して、確定した区間だけを書き起こしへ渡す。

仕様（§8 と §6 のタイマー定数）そのまま:
  - webrtcvad モード 2 / 30ms フレーム
  - 発話開始後の無音で終端。長さは**暗騒音で決める**（静かなら 700ms / うるさければ 1,200ms）
  - 1発話が 30秒 を超えたら強制終了

**ここに書き起こしは含めない。** モデルの読み込みは重く、テストで回せなく
なるので、切り出しだけを純粋な処理として分けてある。
"""
import array
from collections import deque
from dataclasses import dataclass, field
import math

import webrtcvad


SAMPLE_RATE = 16_000
SAMPLE_BYTES = 2                      # Int16 LE
FRAME_MS = 30                         # webrtcvad が受け付けるのは 10/20/30ms だけ
FRAME_BYTES = SAMPLE_RATE * SAMPLE_BYTES * FRAME_MS // 1000   # 960
VAD_MODE = 2                          # §8「モード 2」
SILENCE_MS = 1_200                    # §6 VAD_SILENCE_MS（うるさい部屋の既定）
# 静かな部屋では、これだけ待てば言い終わっている（2026-09-08）。
# うるさいと webrtcvad の判定が細かく途切れるので、短くすると文の途中で切れる。
# **暗騒音で選ぶ。** 固定値を短くするのではなく、環境で分ける
SILENCE_MS_QUIET = 700
# 暗騒音の RMS（Int16）。これ以下なら「静か」。実測ではなく webrtcvad が
# 無音と言い続ける程度の水準として置いた初期値で、実機ログが出たら動かす
QUIET_NOISE_RMS = 300.0
# 暗騒音の移動平均の重み。話していないフレームだけで更新する
NOISE_WEIGHT = 0.1
MAX_UTTERANCE_MS = 30_000             # §6 UTTERANCE_MAX_MS
# 発話開始と判定する前の音も拾う。頭が切れると「はい」などの短い返事が消える
PREROLL_MS = 300
# これより短いものは発話にしない。指パッチンの音そのものを VAD が声と拾い、
# 0.09秒の断片を書き起こそうとして空振りしていた（2026-08-31、実機のログ）。
# 「はい」は 300ms 前後あるので、それを消さない範囲に置く
MIN_UTTERANCE_MS = 250
# ここまでの長さで、かつ書き起こしが空だったものは「物音」とみなす。
# **「聞き取れませんでした」を出さずに、黙って聞き続ける。**
# 拍手の残響が MIN_UTTERANCE_MS を越えて発話として確定し（実機で 360ms）、
# 中身が無いので毎回エラーになり、そのたびに聞き取り直し＝カードの再オープンで
# 光の1周が撃ち直されて「ずっと回っている」ように見えていた（2026-09-04）。
# 本当に話しかけて聞き取れなかったときは、これより長くなるのでエラーが出る
NOISE_UTTERANCE_MS = 700


def frame_rms(frame: bytes) -> float:
    """フレームの実効値。numpy を持ち込まない（この層は切り出しだけ）。"""
    samples = array.array("h")
    samples.frombytes(frame[:len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def silence_target_ms(noise_rms: float) -> int:
    """暗騒音から、終端と判定する無音の長さを決める。"""
    return SILENCE_MS_QUIET if noise_rms <= QUIET_NOISE_RMS else SILENCE_MS


@dataclass
class Utterance:
    """確定した1発話。"""
    pcm: bytes
    ms: int
    reason: str                       # "silence" | "max-length"


@dataclass
class SpeechSplitter:
    """PCM を流し込むと、発話が終わったところで Utterance を返す。

    使い方:
        splitter = SpeechSplitter()
        for chunk in incoming:
            for utterance in splitter.feed(chunk):
                ...
    """
    vad: webrtcvad.Vad = field(default_factory=lambda: webrtcvad.Vad(VAD_MODE))
    _tail: bytes = b""                # フレーム長に満たない端数
    _preroll: deque[bytes] = field(default_factory=lambda: deque(maxlen=max(1, PREROLL_MS // FRAME_MS)))
    _voiced: list[bytes] = field(default_factory=list)
    _silence_ms: int = 0
    _speaking: bool = False
    _noise_rms: float = 0.0           # 話していないあいだの暗騒音（移動平均）
    _silence_target: int = SILENCE_MS  # この発話の終端に使う無音の長さ

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def noise_rms(self) -> float:
        return self._noise_rms

    @property
    def silence_target(self) -> int:
        """いま終端に使っている無音の長さ。デバッグ表示と検証用。"""
        return self._silence_target

    def feed(self, chunk: bytes) -> list[Utterance]:
        """届いた PCM を足して、確定した発話があれば返す。"""
        done: list[Utterance] = []
        data = self._tail + chunk
        offset = 0
        while offset + FRAME_BYTES <= len(data):
            frame = data[offset:offset + FRAME_BYTES]
            offset += FRAME_BYTES
            done.extend(self._push(frame))
        self._tail = data[offset:]
        return done

    def flush(self) -> Utterance | None:
        """接続が切れたときなど、途中の発話を確定させる。"""
        if not self._speaking or not self._voiced:
            self.reset()
            return None
        utterance = self._build("disconnect")
        self.reset()
        return utterance if utterance.ms >= MIN_UTTERANCE_MS else None

    def reset(self) -> None:
        """発話の途中経過だけ捨てる。**暗騒音は残す**（部屋は変わっていない）。"""
        self._tail = b""
        self._preroll.clear()
        self._voiced.clear()
        self._silence_ms = 0
        self._speaking = False

    # --- 以下は内部 ---

    def _push(self, frame: bytes) -> list[Utterance]:
        speech = self.vad.is_speech(frame, SAMPLE_RATE)

        if not self._speaking:
            self._preroll.append(frame)
            if not speech:
                # 話していないフレームだけで暗騒音を測る。声を混ぜると床が上がる
                self._noise_rms += (frame_rms(frame) - self._noise_rms) * NOISE_WEIGHT
                return []
            # 発話開始。直前の数フレームも頭に付けて、語頭が切れないようにする
            self._speaking = True
            self._voiced = list(self._preroll)
            self._preroll.clear()
            self._silence_ms = 0
            # 終端の長さは**発話の頭で決めて固定する。** 途中で変えると、
            # 同じ無音が長さの境目をまたいで判定が揺れる
            self._silence_target = silence_target_ms(self._noise_rms)
            return []

        self._voiced.append(frame)
        self._silence_ms = 0 if speech else self._silence_ms + FRAME_MS

        if self._silence_ms >= self._silence_target:
            utterance = self._build("silence")
            self.reset()
            # 短すぎるものは物音とみなして捨てる（書き起こしへ渡さない）
            return [utterance] if utterance.ms >= MIN_UTTERANCE_MS else []

        if self._length_ms() >= MAX_UTTERANCE_MS:
            utterance = self._build("max-length")
            self.reset()
            return [utterance]
        return []

    def _length_ms(self) -> int:
        return len(self._voiced) * FRAME_MS

    def _build(self, reason: str) -> Utterance:
        # 終端の無音は落とす。書き起こしに渡す意味がなく、時間だけ食う
        keep = self._voiced
        if reason == "silence":
            drop = self._silence_ms // FRAME_MS
            keep = self._voiced[:-drop] if drop and drop < len(self._voiced) else self._voiced
        return Utterance(pcm=b"".join(keep), ms=len(keep) * FRAME_MS, reason=reason)
