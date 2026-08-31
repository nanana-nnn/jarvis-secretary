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

  async start(): Promise<void> {
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
