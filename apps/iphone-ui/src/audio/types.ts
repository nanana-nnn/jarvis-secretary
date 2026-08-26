export interface AudioMetrics { at: number; rms: number; hfRatio: number; riseMs: number }
export interface ClapLog extends AudioMetrics { accepted: boolean; reason: string }
export interface ClapSettings { ratio: number; hfMin: number; gapMin: number; gapMax: number; mode: "double" | "single" }
export const DEFAULT_CLAP_SETTINGS: ClapSettings = { ratio: 6, hfMin: 0.35, gapMin: 150, gapMax: 1100, mode: "double" };
