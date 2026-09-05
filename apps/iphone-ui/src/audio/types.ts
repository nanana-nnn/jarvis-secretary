export interface AudioMetrics { at: number; rms: number; hfRatio: number; riseMs: number }
export interface ClapLog extends AudioMetrics { accepted: boolean; reason: string }
export interface ClapSettings { ratio: number; hfMin: number; gapMin: number; gapMax: number; mode: "double" | "single" }
// 起動方式の真値はここ（2026-09-05、本人の指定で "single" へ戻した）。
// 2026-09-02 に "double" にしたのはタイピング音の誤起動が理由で、
// 9/5 のログでも single 相当の判定は 14回 → 52回に増える見込みだった。
// **誤起動が続くようなら ratio / hfMin を上げて対処する。**
// mode を勝手に戻さないこと（本人の指定が優先）
export const DEFAULT_CLAP_SETTINGS: ClapSettings = { ratio: 6, hfMin: 0.2, gapMin: 250, gapMax: 800, mode: "single" };
