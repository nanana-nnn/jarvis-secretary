import type { AudioMetrics, ClapLog, ClapSettings } from "./types";

export class ClapDetector {
  private noiseFloor = 0.002;
  private firstClapAt = 0;
  private cooldownUntil = 0;
  private logs: ClapLog[] = [];

  constructor(private settings: ClapSettings, private readonly onClap: () => void, private readonly onLog: (logs: ClapLog[]) => void) {}
  update(settings: ClapSettings): void { this.settings = settings; }

  ingest(metric: AudioMetrics): void {
    const alpha = 1 - Math.exp(-128 / 48000 / 3);
    if (metric.rms < this.noiseFloor * 3) this.noiseFloor += alpha * (metric.rms - this.noiseFloor);
    const loud = metric.rms > Math.max(0.008, this.noiseFloor * this.settings.ratio);
    if (!loud) return;
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
    this.push({ ...metric, accepted, reason: accepted ? "wake" : reason });
    if (accepted) { this.firstClapAt = 0; this.cooldownUntil = metric.at + 2000; this.onClap(); }
  }

  private push(log: ClapLog): void { this.logs = [...this.logs.slice(-29), log]; this.onLog(this.logs); }
}
