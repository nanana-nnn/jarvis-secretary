import { useEffect } from "react";

/**
 * ホーム画面PWAで、body を position:fixed にしても内容が101px下にズレる
 * 症状が再発した（2026-09-02、実機SizeProbeで確認：controls.bottom が
 * 945、画面は844で「余り -101」）。CSS のスクロール禁止は HTML文書の
 * スクロールしか止めない。iOS standalone は WKWebView 側が独自に
 * スクロール位置を持つことがあり、そちらは window.scrollTo でしか
 * リセットできない。起動直後と、フォーカス／表示復帰のたびに強制する。
 */
export function useViewportReset(): void {
  useEffect(() => {
    const reset = () => window.scrollTo(0, 0);
    reset();
    const id = window.setTimeout(reset, 300);   // レイアウト確定後にもう一度
    window.addEventListener("focus", reset);
    window.addEventListener("pageshow", reset);
    document.addEventListener("visibilitychange", reset);
    window.visualViewport?.addEventListener("resize", reset);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener("focus", reset);
      window.removeEventListener("pageshow", reset);
      document.removeEventListener("visibilitychange", reset);
      window.visualViewport?.removeEventListener("resize", reset);
    };
  }, []);
}
