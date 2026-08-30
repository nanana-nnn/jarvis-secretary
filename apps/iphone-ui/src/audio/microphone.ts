import { ClapDetector } from "./clap-detector";
import type { AudioMetrics } from "./types";

export class ClapMicrophone {
  private context?: AudioContext;
  private stream?: MediaStream;
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
    await this.context.resume();
  }
  async stop(): Promise<void> { this.stream?.getTracks().forEach(track => track.stop()); await this.context?.close(); }
}
