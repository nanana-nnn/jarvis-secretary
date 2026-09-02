import { ClapDetector } from "./clap-detector";
import type { AudioMetrics } from "./types";

/**
 * マイクは1本だけ開く（DESIGN.md §8「同じストリームを手拍子検出と共用する」）。
 * 同じ source から2つの worklet へ分岐させ、
 *   clap-metrics    … 指パッチン検出用の指標
 *   pcm-downsampler … 16kHz mono Int16 LE（送信用。既定では止めてある）
 * を取り出す。録音は LISTENING の間だけ開く（§8/§6）。
 */
export class ClapMicrophone {
  private context?: AudioContext;
  private stream?: MediaStream;
  private pcm?: AudioWorkletNode;

  constructor(
    private readonly detector: ClapDetector,
    private readonly onPcm?: (chunk: ArrayBuffer) => void,
  ) {}

  /** マイクが実際に動いているか。止まっていれば理由を返す */
  health(): { ok: boolean; context: string; track: string; muted: boolean } {
    const track = this.stream?.getAudioTracks()[0];
    const context = this.context?.state ?? "none";
    return {
      ok: context === "running" && track?.readyState === "live" && !track.muted,
      context,
      track: track?.readyState ?? "none",
      muted: !!track?.muted,
    };
  }

  /**
   * 止まっていたら起こし直す。
   *
   * iOS は音声を再生すると録音セッションを中断することがある
   * （DESIGN.md §20 が挙げている Apple の「アプリ停止時の音声セッション中断」）。
   * 実機で、読み上げのあと指パッチンを一切拾わなくなった（2026-08-31）。
   * resume() はユーザー操作なしでは拒まれることがあるので、
   * 戻り値で「起こせなかった」ことが分かるようにしてある。
   */
  async ensureRunning(): Promise<boolean> {
    if (!this.context) return false;
    const session = (navigator as unknown as { audioSession?: { type: string } }).audioSession;
    if (session) {
      try { session.type = "play-and-record"; } catch { /* 非対応環境 */ }
    }
    if (this.health().ok) return true;

    // まず軽い方から。中断なら resume で戻ることもある
    if (this.context.state !== "running") {
      try { await this.context.resume(); } catch { /* 次の巡回でまた試す */ }
    }
    if (this.health().ok) return true;

    // resume では戻らない。実機は context=interrupted / track.muted=true で、
    // トラックは live のままだった（2026-08-31 のログ）。この形は
    // 開き直さないと復帰しないので、getUserMedia から取り直す
    try { await this.restart(); } catch { return false; }
    return this.health().ok;
  }

  private async restart(): Promise<void> {
    await this.stop();
    this.context = undefined;
    this.stream = undefined;
    this.pcm = undefined;
    await this.start();
  }

  async start(): Promise<void> {
    // 「再生しながら録音する」と宣言する。既定では読み上げのたびに iOS が
    // 録音セッションを中断し、マイクがミュートされたまま戻らなくなる。
    // Safari 16.4 以降。無い環境では黙って飛ばす
    const session = (navigator as unknown as { audioSession?: { type: string } }).audioSession;
    if (session) {
      try { session.type = "play-and-record"; } catch { /* 対応していなければ従来どおり */ }
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      video: false,
    });
    this.context = new AudioContext();
    await this.context.audioWorklet.addModule("/clap-worklet.js");
    const source = this.context.createMediaStreamSource(this.stream);

    const clap = new AudioWorkletNode(this.context, "clap-metrics");
    clap.port.onmessage = (event: MessageEvent<AudioMetrics>) => {
      this.detector.ingest({ ...event.data, at: Date.now() });
    };

    // 送信用。enabled を送るまで何も出さないので、待機中は無駄が出ない
    const pcm = new AudioWorkletNode(this.context, "pcm-downsampler");
    pcm.port.onmessage = (event: MessageEvent<ArrayBuffer>) => this.onPcm?.(event.data);
    this.pcm = pcm;

    // worklet は出力を繋がないと動かない実装があるので、無音のゲイン経由で繋ぐ
    const silent = this.context.createGain();
    silent.gain.value = 0;
    source.connect(clap).connect(silent);
    source.connect(pcm).connect(silent);
    silent.connect(this.context.destination);
    await this.context.resume();
  }

  /** 録音の開始・停止。LISTENING の間だけ true にする */
  setRecording(on: boolean): void {
    this.pcm?.port.postMessage({ enabled: on });
  }

  async stop(): Promise<void> {
    this.stream?.getTracks().forEach(track => track.stop());
    await this.context?.close();
  }
}
