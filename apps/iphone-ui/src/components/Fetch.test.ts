import { describe, expect, it } from "vitest";
import { wakeRow, WAKE_GLYPHS } from "./Fetch";
import { ABSOLUTE_MIN_RMS } from "../audio/clap-detector";
import type { ClapLog } from "../audio/types";

const log = (rms: number, accepted = false): ClapLog =>
  ({ at: 0, rms, hfRatio: .5, riseMs: 5, accepted, reason: accepted ? "wake" : "x" });

describe("wakeRow", () => {
  it("keeps the column count so the 37-wide box cannot break", () => {
    // 桁が1つでもずれると罫線が崩れる。数が足りなくても余っても幅は同じ
    expect(wakeRow([], 22)).toHaveLength(22);
    expect(wakeRow(Array.from({ length: 50 }, () => log(.01)), 22)).toHaveLength(22);
  });

  it("uses only glyphs measured to have the same advance as the rest of the box", () => {
    // **見た目で字を選ばない。** ▁▂▃ などは同梱フォントに無く、別フォントの
    // 15.2px（基準は9px）に落ちて箱の右側が壊れた（2026-09-05 実測）
    const row = wakeRow([log(.001), log(.05), log(.05, true)], 22);
    for (const ch of row) expect(WAKE_GLYPHS).toContain(ch);
  });

  it("shows the newest on the right", () => {
    const row = wakeRow([log(.001), log(ABSOLUTE_MIN_RMS * 3)], 22);
    expect(row.at(-1)).toBe("▄");
    expect(row.at(-2)).toBe("_");
  });

  it("splits on the same threshold the detector uses", () => {
    // 画面の棒と実際の判定をずらさない
    expect(wakeRow([log(ABSOLUTE_MIN_RMS)], 22).at(-1)).toBe("▄");
    expect(wakeRow([log(ABSOLUTE_MIN_RMS - 0.001)], 22).at(-1)).toBe("_");
  });

  it("marks the accepted wake apart from a merely loud noise", () => {
    expect(wakeRow([log(ABSOLUTE_MIN_RMS * 9)], 22).at(-1)).toBe("▄");
    expect(wakeRow([log(ABSOLUTE_MIN_RMS, true)], 22).at(-1)).toBe("█");
  });
});
