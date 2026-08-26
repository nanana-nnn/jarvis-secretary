import { describe, expect, it } from "vitest";
import { transition } from "./machine";

describe("secretary state machine", () => {
  it("follows the Phase 0/1 wake path", () => {
    expect(transition("BOOTING", "CONNECTED")).toBe("SLEEP");
    expect(transition("SLEEP", "CLAP_DETECTED")).toBe("WAKING");
    expect(transition("WAKING", "WAKE_FINISHED")).toBe("LISTENING");
  });
  it("moves every state offline on disconnect", () => expect(transition("THINKING", "DISCONNECTED")).toBe("OFFLINE"));
});
