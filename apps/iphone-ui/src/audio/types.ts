export interface AudioMetrics { at: number; rms: number; hfRatio: number; riseMs: number }
export interface ClapLog extends AudioMetrics { accepted: boolean; reason: string }
export interface ClapSettings { ratio: number; hfMin: number; gapMin: number; gapMax: number; mode: "double" | "single" }
export const DEFAULT_CLAP_SETTINGS: ClapSettings = { ratio: 6, hfMin: 0.2, gapMin: 250, gapMax: 800, mode: "double" };
