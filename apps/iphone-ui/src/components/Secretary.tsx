import type { SecretaryState } from "../states/types";

const OPEN_EYED: SecretaryState[] = ["WAKING", "LISTENING", "TRANSCRIBING", "THINKING", "APPROVAL", "SPEAKING"];

/**
 * 右半分に固定する顔。DESIGN.md §15 のとおり位置・画角は状態で動かさない。
 * 変えるのは目（2枚のクロスフェード）と枠まわりの計器だけ。
 */
export function Secretary({ state }: { state: SecretaryState }) {
  const awake = OPEN_EYED.includes(state);
  return <div className="face">
    <div className="face-frame">
      <img src="/assets/secretary-sleep.png" alt="" />
      <img className={awake ? "awake" : ""} src="/assets/secretary-awake.png" alt="" />
      <div className="face-feather" aria-hidden="true" />
      <div className="face-marks" aria-hidden="true"><i /><i /><i /><i /></div>
    </div>
  </div>;
}
