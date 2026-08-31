import type { AudioMetrics, ClapLog, ClapSettings } from "./types";

export class ClapDetector {
  private noiseFloor = 0.002;
  private firstClapAt = 0;
  private cooldownUntil = 0;
  private lastQuietLogAt = 0;
  private logs: ClapLog[] = [];

  constructor(private settings: ClapSettings, private readonly onClap: () => void, private readonly onLog: (logs: ClapLog[]) => void) {}
  update(settings: ClapSettings): void { this.settings = settings; }

  ingest(metric: AudioMetrics): void {
    const alpha = 1 - Math.exp(-128 / 48000 / 3);
    if (metric.rms < this.noiseFloor * 3) this.noiseFloor += alpha * (metric.rms - this.noiseFloor);
    const threshold = Math.max(0.008, this.noiseFloor * this.settings.ratio);
    const loud = metric.rms > threshold;
    // しきい値に届かなかったものも、たまに記録する。ここで黙って捨てていると
    // 「指パッチンが効かない」ときに何も残らず、原因が分からない
    // （2026-08-31、待機へ戻ったあと反応しなくなった件の切り分け用）
    if (!loud) {
      if (metric.rms > threshold * 0.5 && metric.at - this.lastQuietLogAt > 1000) {
        this.lastQuietLogAt = metric.at;
        this.push({ ...metric, accepted: false, reason: `too quiet (rms ${metric.rms.toFixed(4)} <= ${threshold.toFixed(4)}, floor ${this.noiseFloor.toFixed(4)})` });
      }
      return;
    }
    const spectral = metric.hfRatio >= this.settings.hfMin;
    const sharp = metric.riseMs <= 20;
    let accepted = false;
    let reason = "candidate";
    if (metric.at < this.cooldownUntil) reason = "cooldown";
    else if (!spectral) reason = "low high-frequency ratio";
    else if (!sharp) reason = "slow rise";
    else if (this.settings.mode === "single") accepted = true;
    else if (!this.firstClapAt || metric.at - this.firstClapAt > this.settings.gapMax) { this.firstClapAt = metric.at; reason = "first clap"; }
    else if (metric.at - this.firstClapAt < this.settings.gapMin) reason = "gap too short";
    else accepted = true;
    this.push({ ...metric, accepted, reason: accepted ? "wake" : `${reason} (floor ${this.noiseFloor.toFixed(4)})` });
    if (accepted) { this.firstClapAt = 0; this.cooldownUntil = metric.at + 2000; this.onClap(); }
  }

  private push(log: ClapLog): void { this.logs = [...this.logs.slice(-29), log]; this.onLog(this.logs); }
}
