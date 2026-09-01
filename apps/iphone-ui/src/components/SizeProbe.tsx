import { useEffect, useState } from "react";

/**
 * 実機の寸法を画面に出すだけの確認用オーバーレイ。`?size=1`、または DEBUG（•••）で出る。
 *
 * 画面下の余白は、ヘッドレスブラウザでは再現しない要因（`env(safe-area-inset-*)`、
 * Safari のツールバー、dvh と lvh の差）が絡むので、こちらの実測では詰められない。
 * 実機の値を1枚のスクショで持ち帰るために置く。原因が確定したら消す。
 *
 * DEBUG からも出すのは、ホーム画面 PWA では `?size=1` が届かないため
 * （manifest の start_url が "/" なので起動時にクエリが落ちる。加えて
 * `previewable` ゲートが静的ビルドでは閉じている）。崩れているのが standalone の
 * ときだけなので、そこで測れないと原因が確定しない（2026-09-01）。
 */
export function SizeProbe() {
  const [rows, setRows] = useState<string[]>([]);

  useEffect(() => {
    const read = () => {
      const probe = document.createElement("div");
      probe.style.cssText = "position:fixed;top:0;left:0;width:0;visibility:hidden;"
        + "height:100dvh;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)";
      document.body.appendChild(probe);
      const dvh = probe.getBoundingClientRect().height;
      const probeStyle = getComputedStyle(probe);
      const safeTop = parseFloat(probeStyle.paddingTop) || 0;
      const safeBottom = parseFloat(probeStyle.paddingBottom) || 0;
      probe.style.height = "100lvh";
      const lvh = probe.getBoundingClientRect().height;
      probe.style.height = "100svh";
      const svh = probe.getBoundingClientRect().height;
      probe.remove();

      const el = (sel: string) => document.querySelector(sel) as HTMLElement | null;
      const shell = el(".shell");
      const controls = el(".controls");
      const root = document.getElementById("root");
      const shellStyle = shell ? getComputedStyle(shell) : null;
      const controlsStyle = controls ? getComputedStyle(controls) : null;
      const pad = (style: CSSStyleDeclaration | null, side: "paddingTop" | "paddingBottom") =>
        Math.round(parseFloat(style?.[side] ?? "0") || 0);

      // .shell の grid 4段が実際にどこを取ったか。どの段が溢れているかはここで分かる
      const band = (sel: string, label: string) => {
        const r = el(sel)?.getBoundingClientRect();
        return r ? `${label} ${Math.round(r.top)}→${Math.round(r.bottom)} h${Math.round(r.height)}` : `${label} —`;
      };

      // navigator.standalone だけだと取りこぼすので display-mode も見る
      const standalone = window.matchMedia("(display-mode: standalone)").matches
        || (navigator as unknown as { standalone?: boolean }).standalone === true;

      setRows([
        `standalone ${String(standalone)}  dpr ${window.devicePixelRatio}`,
        `innerHeight ${window.innerHeight}  screen ${window.screen.height}`,
        `dvh ${Math.round(dvh)}  lvh ${Math.round(lvh)}  svh ${Math.round(svh)}`,
        `safe top ${Math.round(safeTop)}  bottom ${Math.round(safeBottom)}`,
        `shell pad ${pad(shellStyle, "paddingTop")}/${pad(shellStyle, "paddingBottom")}`,
        `controls pad-b ${pad(controlsStyle, "paddingBottom")}`,
        `root ${Math.round(root?.getBoundingClientRect().height ?? 0)}  shell ${Math.round(shell?.getBoundingClientRect().height ?? 0)}`,
        band(".fetch", "1 fetch"),
        band(".core-stage", "2 core"),
        band(".live", "3 live"),
        band(".controls", "4 ctrl"),
        `余り ${Math.round(window.innerHeight - (controls?.getBoundingClientRect().bottom ?? 0))}`,
      ]);
    };
    read();
    // standalone は起動直後に safe-area がまだ確定していないことがあるので撮り直す
    const settle = window.setTimeout(read, 600);
    window.addEventListener("resize", read);
    window.addEventListener("orientationchange", read);
    return () => {
      window.clearTimeout(settle);
      window.removeEventListener("resize", read);
      window.removeEventListener("orientationchange", read);
    };
  }, []);

  return <div className="size-probe">{rows.map(r => <div key={r}>{r}</div>)}</div>;
}
