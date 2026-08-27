import type { SecretaryState } from "../states/types";

export function Secretary({ state }: { state: SecretaryState }) {
  const awake = !["BOOTING", "SLEEP", "OFFLINE"].includes(state);
  return <div className={`portrait ${state === "THINKING" ? "thinking" : ""}`}>
    <div className="portrait-glow" aria-hidden="true" />
    <img src="/assets/secretary-sleep.png" aria-hidden={awake} />
    <img className={awake ? "visible" : ""} src="/assets/secretary-awake.png" aria-hidden={!awake} />
    <div className="portrait-scan" aria-hidden="true" />
    <div className="portrait-index" aria-hidden="true"><span>SUBJECT 01</span><b>ONLINE</b></div>
  </div>;
}
