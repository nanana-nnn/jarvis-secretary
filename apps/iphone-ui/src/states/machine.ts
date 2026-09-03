import type { SecretaryEvent, SecretaryState } from "./types";

const transitions: Partial<Record<SecretaryState, Partial<Record<SecretaryEvent, SecretaryState>>>> = {
  BOOTING: { CONNECTED: "SLEEP", CONNECT_FAILED: "OFFLINE", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  SLEEP: { CLAP_DETECTED: "WAKING", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  // IDLE は LISTENING/TRANSCRIBING/SPEAKING と同じ戻り道（下のコメント参照）。
  // 拍手の直後、WAKE_FINISHED が来る前に聞き取り失敗（STT_FAILED）が届くと
  // ここに居る。無いと AWAKENING のまま固まる（2026-09-03、実機で確認）
  WAKING: { WAKE_FINISHED: "LISTENING", AGENT_STARTED: "THINKING", IDLE: "SLEEP", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  LISTENING: { AUDIO_FINAL: "TRANSCRIBING", IDLE: "SLEEP", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  // IDLE は DESIGN.md §6 の表には無いが足してある。エージェントが始まらないと
  // 抜け道が無く、TRANSCRIBING で永久に留まるため（2026-08-31、実機で固まった）。
  // Phase 2 はエージェントがまだ無いので必ずここを通る。Phase 3 以降も
  // エージェントの起動に失敗したときの戻り道として要る。
  TRANSCRIBING: { AGENT_STARTED: "THINKING", IDLE: "SLEEP", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  // THINKING の IDLE は「やめて」による中断（2026-09-02）。SPEAKING（文字回答カード）
  // へ進めて、中断した旨をカードへ表示してから「戻る」で閉じられるようにする。
  // 直接 SLEEP へ落とすと、カードが表示されないまま消えて何が起きたか分からない
  THINKING: { APPROVAL_REQUIRED: "APPROVAL", AGENT_COMPLETED: "SPEAKING", IDLE: "SPEAKING", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  APPROVAL: { AGENT_COMPLETED: "SPEAKING", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  // CONTINUE は文字回答カードの「続けて聞く」（2026-09-02）。WAKING を経由せず
  // 直接 LISTENING へ戻り、次の発話を録る
  SPEAKING: { IDLE: "SLEEP", FINISH: "SLEEP", CONTINUE: "LISTENING", DISCONNECTED: "OFFLINE", SYSTEM_ERROR: "ERROR" },
  ERROR: { RETRY: "SLEEP", DISCONNECTED: "OFFLINE" },
  OFFLINE: { CONNECTED: "SLEEP", SYSTEM_ERROR: "ERROR" },
};

export function transition(state: SecretaryState, event: SecretaryEvent): SecretaryState {
  if (event === "DISCONNECTED") return "OFFLINE";
  if (event === "SYSTEM_ERROR") return "ERROR";
  return transitions[state]?.[event] ?? state;
}
