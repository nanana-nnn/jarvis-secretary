import type { SecretaryState } from "../states/types";

export function Secretary({ state }: { state: SecretaryState }) {
  const awake = !["BOOTING", "SLEEP", "OFFLINE"].includes(state);
  return <div className={`portrait ${state === "THINKING" ? "thinking" : ""}`}>
    <img src="/assets/secretary-sleep.svg" aria-hidden={awake} />
    <img className={awake ? "visible" : ""} src="/assets/secretary-awake.svg" aria-hidden={!awake} />
  </div>;
}
