import type { ClapLog, ClapSettings } from "../audio/types";

export function DebugPanel({ logs, settings, onSettings, onClose }: { logs: ClapLog[]; settings: ClapSettings; onSettings: (s: ClapSettings) => void; onClose: () => void }) {
  const numberField = (key: "ratio" | "hfMin" | "gapMin" | "gapMax", min: number, max: number, step: number) =>
    <label>{key}<input type="number" value={settings[key]} min={min} max={max} step={step} onChange={e => onSettings({ ...settings, [key]: Number(e.target.value) })} /></label>;
  // このパネルは画面全体を覆う(z-index 20)。下の操作列にある ••• は隠れて
  // 押せないので、閉じる口をここに持つ（2026-09-02、実機で戻れなくなった）
  return <section className="debug">
    <button className="debug-close" onClick={onClose} aria-label="CLOSE DEBUG LOG">CLOSE ✕</button>
    <div className="settings">{numberField("ratio",3,15,.1)}{numberField("hfMin",.15,.7,.01)}{numberField("gapMin",100,300,10)}{numberField("gapMax",500,1500,10)}</div>
    <ol>{[...logs].reverse().map((x, i) => <li key={`${x.at}-${i}`} className={x.accepted ? "accepted" : ""}>{new Date(x.at).toLocaleTimeString()} RMS {x.rms.toFixed(3)} / HF {x.hfRatio.toFixed(2)} — {x.reason}</li>)}</ol>
  </section>;
}
