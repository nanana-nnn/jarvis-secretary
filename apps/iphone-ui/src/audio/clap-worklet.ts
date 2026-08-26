declare const currentTime: number;
declare const sampleRate: number;
declare abstract class AudioWorkletProcessor {
  readonly port: MessagePort;
  abstract process(inputs: Float32Array[][]): boolean;
}
declare function registerProcessor(name: string, processor: typeof AudioWorkletProcessor): void;

class ClapMetricsProcessor extends AudioWorkletProcessor {
  private lowPass = 0;
  private previousRms = 0;
  private riseStarted = 0;
  process(inputs: Float32Array[][]): boolean {
    const input = inputs[0]?.[0];
    if (!input?.length) return true;
    let energy = 0, highEnergy = 0;
    const alpha = Math.exp(-2 * Math.PI * 4000 / sampleRate);
    for (const sample of input) {
      energy += sample * sample;
      this.lowPass = (1 - alpha) * sample + alpha * this.lowPass;
      const highPassed = sample - this.lowPass;
      highEnergy += highPassed * highPassed;
    }
    const rms = Math.sqrt(energy / input.length);
    if (rms > this.previousRms * 1.5 && !this.riseStarted) this.riseStarted = currentTime;
    const riseMs = this.riseStarted ? (currentTime - this.riseStarted) * 1000 : 999;
    if (rms < this.previousRms) this.riseStarted = 0;
    this.previousRms = rms;
    this.port.postMessage({ at: 0, rms, hfRatio: Math.min(1, highEnergy / Math.max(energy, 1e-12)), riseMs });
    return true;
  }
}
registerProcessor("clap-metrics", ClapMetricsProcessor);
