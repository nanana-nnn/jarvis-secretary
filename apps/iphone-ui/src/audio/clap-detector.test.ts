import { describe, expect, it, vi } from "vitest";
import { ClapDetector } from "./clap-detector";
import { DEFAULT_CLAP_SETTINGS } from "./types";

// 起動方式は本人の指定で入れ替わる（2026-09-02 double / 2026-09-05 single）。
// **既定に寄りかからず、どちらの道もそれぞれ固定する。**
const DOUBLE = { ...DEFAULT_CLAP_SETTINGS, mode: "double" } as const;
const SINGLE = { ...DEFAULT_CLAP_SETTINGS, mode: "single" } as const;

describe("ClapDetector", () => {
  it("wakes on a single valid candidate when the mode is single", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(SINGLE, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .1, hfRatio: .6, riseMs: 10 });
    expect(wake).toHaveBeenCalledOnce();
  });
  it("uses the shipped default so the wake gesture is pinned to types.ts", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DEFAULT_CLAP_SETTINGS, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .1, hfRatio: .6, riseMs: 10 });
    // 既定が single なら1回で起きる。double へ戻したらここが落ちて気づける
    expect(wake).toHaveBeenCalledTimes(DEFAULT_CLAP_SETTINGS.mode === "single" ? 1 : 0);
  });
  it("wakes on two valid candidates in the configured gap", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DOUBLE, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .1, hfRatio: .6, riseMs: 10 });
    expect(wake).not.toHaveBeenCalled();
    detector.ingest({ at: 1600, rms: .1, hfRatio: .6, riseMs: 10 });
    expect(wake).toHaveBeenCalledOnce();
  });
  it("rejects two claps outside the configured 800ms window", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DOUBLE, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .1, hfRatio: .6, riseMs: 10 });
    detector.ingest({ at: 1900, rms: .1, hfRatio: .6, riseMs: 10 });
    expect(wake).not.toHaveBeenCalled();
  });
  it("rejects a low-frequency candidate", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DEFAULT_CLAP_SETTINGS, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .1, hfRatio: .1, riseMs: 10 });
    detector.ingest({ at: 1600, rms: .1, hfRatio: .1, riseMs: 10 });
    expect(wake).not.toHaveBeenCalled();
  });
  it("rejects the measured keyboard peak even when it is sharp and high-frequency", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DEFAULT_CLAP_SETTINGS, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .016, hfRatio: .53, riseMs: 2 });
    expect(wake).not.toHaveBeenCalled();
  });
});
