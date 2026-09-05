/**
 * 手拍子の閾値は端末内に持つ。**起動方式は毎回上書きする。**
 * 端末に残った古い mode に負けないようにするための上書きで、
 * 値は `DEFAULT_CLAP_SETTINGS.mode` に従う（2026-09-05、指パッチン1回へ戻した）。
 */
import { DEFAULT_CLAP_SETTINGS, type ClapSettings } from "./audio/types";

const KEY = "clap-settings";

export function loadClapSettings(): ClapSettings {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    return { ...DEFAULT_CLAP_SETTINGS, ...saved, hfMin: 0.2, gapMin: 250, gapMax: 800,
             mode: DEFAULT_CLAP_SETTINGS.mode };
  } catch {
    return { ...DEFAULT_CLAP_SETTINGS };
  }
}

export function saveClapSettings(settings: ClapSettings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    // Safari のプライベートモードは保存を拒否する。検出自体はメモリ上の設定で続く
  }
}
