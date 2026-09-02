import type { SecretaryEvent, SecretaryState } from "./types";

const transitions: Partial<Record<SecretaryState, Partial<Record<SecretaryEvent, SecretaryState>>>> = {
  BOOTING: { CONNECTED: "SLEEP", CONNECT_FAILED: "OFFLINE", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  SLEEP: { CLAP_DETECTED: "WAKING", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  WAKING: { WAKE_FINISHED: "LISTENING", AGENT_STARTED: "THINKING", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  LISTENING: { AUDIO_FINAL: "TRANSCRIBING", IDLE: "SLEEP", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  // IDLE は DESIGN.md §6 の表には無いが足してある。エージェントが始まらないと
  // 抜け道が無く、TRANSCRIBING で永久に留まるため（2026-08-31、実機で固まった）。
  // Phase 2 はエージェントがまだ無いので必ずここを通る。Phase 3 以降も
  // エージェントの起動に失敗したときの戻り道として要る。
  TRANSCRIBING: { AGENT_STARTED: "THINKING", IDLE: "SLEEP", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  THINKING: { APPROVAL_REQUIRED: "APPROVAL", AGENT_COMPLETED: "SPEAKING", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  APPROVAL: { AGENT_COMPLETED: "SPEAKING", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  SPEAKING: { IDLE: "SLEEP", FINISH: "SLEEP", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  ERROR: { RETRY: "SLEEP", DISCONNECTED: "OFFLINE" },
  OFFLINE: { CONNECTED: "SLEEP", SYSTEM_ERROR: "ERROR" },
};

export function transition(state: SecretaryState, event: SecretaryEvent): SecretaryState {
  if (event === "DISCONNECTED") return "OFFLINE";
  if (event === "SYSTEM_ERROR") return "ERROR";
  return transitions[state]?.[event] ?? state;
}
