/**
 * 状態ごとの表示文。DESIGN.md §15: 画面上の文字はすべて英語、短い状態名だけにする。
 * code は状態の系統が一目で分かるよう接頭辞を揃えてある（SYS / COM / AI / SEC / ERR / NET）。
 */
import type { SecretaryState } from "./states/types";

export type StateCopy = { en: string; code: string };

export const copy: Record<SecretaryState, StateCopy> = {
  BOOTING:      { en: "INITIALIZING",  code: "SYS.00" },
  SLEEP:        { en: "STANDBY",       code: "SYS.01" },
  WAKING:       { en: "AWAKENING",     code: "SYS.02" },
  LISTENING:    { en: "LISTENING",     code: "COM.10" },
  TRANSCRIBING: { en: "TRANSCRIBING",  code: "COM.11" },
  THINKING:     { en: "REASONING",     code: "AI.20"  },
  APPROVAL:     { en: "AUTHORIZATION", code: "SEC.30" },
  SPEAKING:     { en: "RESPONDING",    code: "COM.12" },
  ERROR:        { en: "RECOVERY",      code: "ERR.90" },
  OFFLINE:      { en: "LINK OFFLINE",  code: "NET.91" },
};
