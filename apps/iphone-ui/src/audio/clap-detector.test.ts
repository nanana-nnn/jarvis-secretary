import { describe, expect, it, vi } from "vitest";
import { ClapDetector } from "./clap-detector";
import { DEFAULT_CLAP_SETTINGS } from "./types";

describe("ClapDetector", () => {
  it("wakes on two valid candidates in the configured gap", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DEFAULT_CLAP_SETTINGS, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .1, hfRatio: .6, riseMs: 10 });
    detector.ingest({ at: 1600, rms: .1, hfRatio: .6, riseMs: 10 });
    expect(wake).toHaveBeenCalledOnce();
  });
  it("rejects a low-frequency candidate", () => {
    const wake = vi.fn();
    const detector = new ClapDetector(DEFAULT_CLAP_SETTINGS, wake, () => undefined);
    detector.ingest({ at: 1000, rms: .1, hfRatio: .1, riseMs: 10 });
    detector.ingest({ at: 1600, rms: .1, hfRatio: .1, riseMs: 10 });
    expect(wake).not.toHaveBeenCalled();
  });
});
