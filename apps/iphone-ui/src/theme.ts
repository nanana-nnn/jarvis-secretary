/**
 * サーバーから届いた配色と壁紙を、実際の画面へ反映する（DESIGN.md §15）。
 *
 * ここだけが `document` を直接触る。**届いた値は信頼せず形だけ見る**：
 * Material トークンが1つでも欠けたら配色ごと捨てて、前の見た目を残す。
 */

// サーバーから来る差し色を検査する。信頼せずに形だけ見る。
const HEX = /^#[0-9a-f]{6}$/i;

export type Scheme = {
  mode: "light" | "dark";
  background: string;
  surfaceContainer: string;
  surfaceContainerHigh: string;
  onSurface: string;
  onSurfaceVariant: string;
  outlineVariant: string;
  primary: string;
  onPrimary: string;
  error: string;
};

const schemeVariables: Record<Exclude<keyof Scheme, "mode">, string> = {
  background: "--scheme-bg",
  surfaceContainer: "--scheme-surface",
  surfaceContainerHigh: "--scheme-surface-high",
  onSurface: "--scheme-text",
  onSurfaceVariant: "--scheme-muted",
  outlineVariant: "--scheme-outline",
  primary: "--scheme-primary",
  onPrimary: "--scheme-on-primary",
  error: "--scheme-error",
};

/**
 * 端末のANSI色。文字回答カードのプロンプト行を `~/.config/starship.toml` と
 * 同じ配色にするために使う（2026-09-02、本人の指定「実際のターミナルと
 * 同じように」）。caelestia が壁紙から作る term0〜term15 の一部で、
 * 壁紙を変えるとこちらも変わる。
 * **任意扱い。** 届かなければ CSS 側の既定値のままにする（既定値は
 * :root にあり、Material トークンから作ってあるので無色にはならない）
 */
const termVariables: Record<string, string> = {
  term0: "--term-black",
  term3: "--term-yellow",
  term6: "--term-cyan",
  term7: "--term-white",
  term12: "--term-blue",
};

/** 配色を反映する。欠けていたら何もしない（前の配色を残す）。 */
export function applyScheme(value: unknown): void {
  if (!value || typeof value !== "object") return;
  const scheme = value as Partial<Scheme>;
  const valid = (scheme.mode === "light" || scheme.mode === "dark")
    && Object.keys(schemeVariables).every(key => typeof scheme[key as keyof Scheme] === "string" && HEX.test(String(scheme[key as keyof Scheme])));
  if (!valid) return;

  document.documentElement.dataset.theme = scheme.mode;
  for (const [key, variable] of Object.entries(schemeVariables)) {
    document.documentElement.style.setProperty(variable, String(scheme[key as keyof Scheme]));
  }
  // 端末のANSI色は任意。届いたものだけ差し替える（届かなければ
  // CSS の既定値のまま。プロンプト行が無色にならないようにする）
  const raw = scheme as unknown as Record<string, unknown>;
  for (const [key, variable] of Object.entries(termVariables)) {
    const colour = raw[key];
    if (typeof colour === "string" && HEX.test(colour)) {
      document.documentElement.style.setProperty(variable, colour);
    }
  }
  // Safari はツールバーと status bar をこの色で塗る。固定値のままだと
  // 配色と合わず、画面の下に黒い帯が残る（2026-08-31、実機で約1cm）
  document.querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", String(scheme.background));
}

/**
 * 壁紙を差し替える。版つきのURLで取り直す（同じ版ならブラウザの控えが効く）。
 * 版が空＝サーバー側の変換に失敗しているので、壁紙なしへ戻す。
 */
export function applyWallpaper(version: unknown): void {
  const tag = typeof version === "string" ? version : "";
  document.documentElement.style.setProperty(
    "--wallpaper", tag ? `url("/wallpaper.webp?v=${tag}")` : "none");
}
