import type { SecretaryState } from "../states/types";

const OPEN_EYED = new Set<SecretaryState>(["WAKING", "LISTENING", "TRANSCRIBING", "THINKING", "APPROVAL", "SPEAKING"]);

export function Secretary({ state }: { state: SecretaryState }) {
  const awake = OPEN_EYED.has(state);
  return <section className="portrait" aria-label="AI秘書ビジュアル">
    <div className="portrait-aura" aria-hidden="true"><i /><i /><i /></div>
    <div className="portrait-frame">
      <img className="portrait-sleep" src="/assets/secretary-sleep.webp" alt="" />
      <img className={`portrait-awake ${awake ? "is-visible" : ""}`} src="/assets/secretary-awake.webp" alt="" />
      <div className="iris-pulse" aria-hidden="true" />
      <div className="portrait-grade" aria-hidden="true" />
      <div className="scan-beam" aria-hidden="true" />
    </div>
    <div className="portrait-id"><span>JVS–01</span><strong>SECRETARY CORE</strong><small>VISUAL COGNITION ONLINE</small></div>
    <span className="corner corner-nw" aria-hidden="true" /><span className="corner corner-se" aria-hidden="true" />
  </section>;
}
