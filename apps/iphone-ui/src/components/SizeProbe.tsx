import { useEffect, useState } from "react";

/**
 * 実機の寸法を画面に出すだけの確認用オーバーレイ。`?size=1` でのみ出る。
 *
 * 画面下の余白は、ヘッドレスブラウザでは再現しない要因（`env(safe-area-inset-*)`、
 * Safari のツールバー、dvh と lvh の差）が絡むので、こちらの実測では詰められない。
 * 実機の値を1枚のスクショで持ち帰るために置く。原因が確定したら消す。
 */
export function SizeProbe() {
  const [rows, setRows] = useState<string[]>([]);

  useEffect(() => {
    const read = () => {
      const probe = document.createElement("div");
      probe.style.cssText = "position:fixed;top:0;left:0;width:0;visibility:hidden;"
        + "height:100dvh;padding-bottom:env(safe-area-inset-bottom)";
      document.body.appendChild(probe);
      const dvh = probe.getBoundingClientRect().height;
      const safeBottom = parseFloat(getComputedStyle(probe).paddingBottom) || 0;
      probe.style.height = "100lvh";
      const lvh = probe.getBoundingClientRect().height;
      probe.style.height = "100svh";
      const svh = probe.getBoundingClientRect().height;
      probe.remove();

      const shell = document.querySelector(".shell")?.getBoundingClientRect();
      const controls = document.querySelector(".controls")?.getBoundingClientRect();
      const root = document.getElementById("root")?.getBoundingClientRect();

      setRows([
        `innerHeight ${window.innerHeight}`,
        `dvh ${Math.round(dvh)}  lvh ${Math.round(lvh)}  svh ${Math.round(svh)}`,
        `safe-bottom ${Math.round(safeBottom)}`,
        `root ${Math.round(root?.height ?? 0)}  shell ${Math.round(shell?.height ?? 0)}`,
        `controls底 ${Math.round(controls?.bottom ?? 0)}`,
        `余り ${Math.round(window.innerHeight - (controls?.bottom ?? 0))}`,
        `dpr ${window.devicePixelRatio}  standalone ${String((navigator as unknown as { standalone?: boolean }).standalone ?? false)}`,
      ]);
    };
    read();
    window.addEventListener("resize", read);
    return () => window.removeEventListener("resize", read);
  }, []);

  return <div className="size-probe">{rows.map(r => <div key={r}>{r}</div>)}</div>;
}
