class ClapMetricsProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.lowPass = 0;
    this.previousRms = 0;
    this.riseStarted = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input?.length) return true;
    let energy = 0;
    let highEnergy = 0;
    const alpha = Math.exp((-2 * Math.PI * 4000) / sampleRate);
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
    this.port.postMessage({
      at: 0,
      rms,
      hfRatio: Math.min(1, highEnergy / Math.max(energy, 1e-12)),
      riseMs,
    });
    return true;
  }
}

registerProcessor("clap-metrics", ClapMetricsProcessor);

/**
 * 音声送信用に 16kHz mono Int16 LE を切り出す（DESIGN.md §8「iPhone側」）。
 *
 * MediaRecorder は使わない。Safari の対応形式が不安定なため、生 PCM を取る。
 * 手拍子検出と**同じストリーム**から分岐させる（マイクを二重に開かない）。
 *
 * AudioContext の実サンプルレート（iPhone は 48000 が多い）から 16000 へ
 * 線形補間で落とし、20ms（320サンプル = 640バイト）ごとに送る。
 */
class PcmDownsampler extends AudioWorkletProcessor {
  static get parameterDescriptors() { return []; }

  constructor() {
    super();
    this.enabled = false;
    this.ratio = sampleRate / 16000;   // 例: 48000/16000 = 3
    this.position = 0;                 // 入力側の小数位置
    this.out = new Int16Array(320);    // 20ms ぶん
    this.filled = 0;
    this.port.onmessage = event => { this.enabled = !!event.data?.enabled; };
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input?.length) return true;
    if (!this.enabled) { this.position = 0; this.filled = 0; return true; }

    // 線形補間で 16kHz へ間引く。位置はブロックをまたいで持ち越す
    while (this.position < input.length) {
      const index = Math.floor(this.position);
      const frac = this.position - index;
      const a = input[index];
      const b = index + 1 < input.length ? input[index + 1] : a;
      const value = a + (b - a) * frac;
      // クリップしてから Int16 へ。歪むより潰れるほうが書き起こしに優しい
      const clamped = Math.max(-1, Math.min(1, value));
      this.out[this.filled++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      if (this.filled === this.out.length) {
        // 転送するとバッファが奪われるので、毎回コピーを渡す
        this.port.postMessage(this.out.slice().buffer, [this.out.slice().buffer]);
        this.filled = 0;
      }
      this.position += this.ratio;
    }
    this.position -= input.length;
    return true;
  }
}

registerProcessor("pcm-downsampler", PcmDownsampler);
