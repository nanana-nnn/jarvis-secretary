import { describe, expect, it } from "vitest";
import { transition } from "./machine";
import type { SecretaryEvent, SecretaryState } from "./types";

describe("secretary state machine", () => {
  it("follows the Phase 0/1 wake path", () => {
    expect(transition("BOOTING", "CONNECTED")).toBe("SLEEP");
    expect(transition("SLEEP", "CLAP_DETECTED")).toBe("WAKING");
    expect(transition("WAKING", "WAKE_FINISHED")).toBe("LISTENING");
  });
  it("moves every state offline on disconnect", () => expect(transition("THINKING", "DISCONNECTED")).toBe("OFFLINE"));
});

describe("行き止まりがないこと", () => {
  it("どの状態からも SLEEP へ戻れる", () => {
    // 実機で TRANSCRIBING に入ったまま抜けられなくなった（2026-08-31）。
    // 「入れるのに出られない状態」を作らないための歯止め。
    const states: SecretaryState[] = [
      "BOOTING", "SLEEP", "WAKING", "LISTENING", "TRANSCRIBING",
      "THINKING", "APPROVAL", "SPEAKING", "ERROR", "OFFLINE",
    ];
    const events: SecretaryEvent[] = [
      "CONNECTED", "CONNECT_FAILED", "DISCONNECTED", "CLAP_DETECTED", "WAKE_FINISHED",
      "AUDIO_FINAL", "AGENT_STARTED", "APPROVAL_REQUIRED", "AGENT_COMPLETED",
      "IDLE", "FINISH", "SYSTEM_ERROR", "RETRY",
    ];

    // 各状態から到達できる先を辿り、SLEEP に着けるかを見る
    for (const start of states) {
      const seen = new Set<SecretaryState>([start]);
      const queue: SecretaryState[] = [start];
      let reached = start === "SLEEP";
      while (queue.length && !reached) {
        const current = queue.shift()!;
        for (const event of events) {
          const next = transition(current, event);
          if (next === "SLEEP") { reached = true; break; }
          if (!seen.has(next)) { seen.add(next); queue.push(next); }
        }
      }
      expect(reached, `${start} から SLEEP へ戻れない`).toBe(true);
    }
  });

  it("TRANSCRIBING は IDLE で待機へ戻る", () => {
    // Phase 2 はエージェントが無いので、読み上げ後はここを通るしかない
    expect(transition("TRANSCRIBING", "IDLE")).toBe("SLEEP");
  });

  it("即答も TRANSCRIBING → THINKING → SPEAKING の順で進む", () => {
    const thinking = transition("TRANSCRIBING", "AGENT_STARTED");
    expect(thinking).toBe("THINKING");
    expect(transition(thinking, "AGENT_COMPLETED")).toBe("SPEAKING");
  });
});
