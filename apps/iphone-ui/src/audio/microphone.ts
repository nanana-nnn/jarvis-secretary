import { ClapDetector } from "./clap-detector";
import type { AudioMetrics } from "./types";

export class ClapMicrophone {
  private context?: AudioContext;
  private stream?: MediaStream;
  private analyser?: AnalyserNode;
  private freq?: Uint8Array<ArrayBuffer>;
  constructor(private readonly detector: ClapDetector, private readonly onMetrics?: (metrics: AudioMetrics) => void) {}
  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }, video: false });
    this.context = new AudioContext();
    await this.context.audioWorklet.addModule("/clap-worklet.js");
    const source = this.context.createMediaStreamSource(this.stream);
    const worklet = new AudioWorkletNode(this.context, "clap-metrics");
    const silent = this.context.createGain(); silent.gain.value = 0;
    worklet.port.onmessage = (event: MessageEvent<AudioMetrics>) => {
      const metrics = { ...event.data, at: Date.now() };
      this.onMetrics?.(metrics);
      this.detector.ingest(metrics);
    };
    source.connect(worklet).connect(silent).connect(this.context.destination);

    // ドットパネル用の20帯域。sysmon-dots.py の cava (BARS=20) 相当を Web Audio の
    // AnalyserNode で代替する。破壊せずに source から分岐するだけなので出力には繋がない
    const analyser = this.context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.55;
    source.connect(analyser);
    this.analyser = analyser;
    this.freq = new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount));

    await this.context.resume();
  }
  // 周波数ビンを20帯域へ間引く。二乗配分で低音側に解像度を寄せる（cava の autosens 相当の簡易近似）
  readBands(count = 20): Float32Array | null {
    if (!this.analyser || !this.freq) return null;
    this.analyser.getByteFrequencyData(this.freq);
    const bins = this.freq.length;
    const bands = new Float32Array(count);
    for (let i = 0; i < count; i += 1) {
      const lo = Math.floor((i / count) ** 2 * bins);
      const hi = Math.max(lo + 1, Math.floor(((i + 1) / count) ** 2 * bins));
      let sum = 0;
      for (let bin = lo; bin < hi && bin < bins; bin += 1) sum += this.freq[bin];
      bands[i] = sum / Math.max(1, hi - lo) / 255;
    }
    return bands;
  }
  async stop(): Promise<void> { this.stream?.getTracks().forEach(track => track.stop()); await this.context?.close(); }
}
