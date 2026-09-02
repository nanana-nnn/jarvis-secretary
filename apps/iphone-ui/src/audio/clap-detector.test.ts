import { describe, expect, it, vi } from "vitest";
import { ClapDetector } from "./clap-detector";
import { DEFAULT_CLAP_SETTINGS } from "./types";

describe("ClapDetector", () => {
  it("wakes on two valid candidates in the configured gap", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DEFAULT_CLAP_SETTINGS, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .1, hfRatio: .6, riseMs: 10 });
    expect(wake).not.toHaveBeenCalled();
    detector.ingest({ at: 1600, rms: .1, hfRatio: .6, riseMs: 10 });
    expect(wake).toHaveBeenCalledOnce();
  });
  it("rejects two claps outside the configured 800ms window", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DEFAULT_CLAP_SETTINGS, wake, () => undefined);
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
