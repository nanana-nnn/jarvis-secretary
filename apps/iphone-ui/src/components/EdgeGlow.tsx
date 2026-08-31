import type { SecretaryState } from "../states/types";

/**
 * 画面の縁が光る演出。
 *
 * ただ光らせると、2段目のドットと同じ「情報量ゼロの面積」が増えるだけなので、
 * **光り方は必ず状態に紐づける**。視界の端だけで状態が分かるのが狙い。
 *
 *   SLEEP        … ゆっくり呼吸する（常設で眩しくならない明るさに抑える）
 *   WAKING       … 起動の瞬間。強く焚いて縁を一周させる（ここは派手にする）
 *   LISTENING    … 明るいまま保つ。聞いている間ずっと点いている
 *   THINKING 他  … 速く脈打つ
 *   ERROR/OFFLINE… 同じ形のまま色だけ error へ寄せる
 *
 * 実装は要素2枚だけ。conic-gradient を回して縁のリングに見せ、内側を
 * 背景色で塗りつぶして枠だけ残す。CSS だけで動くので JS からは触らない
 * （@property は iOS Safari 16.4 未満で効かないため、transform で回す）。
 */
export function EdgeGlow({ state }: { state: SecretaryState }) {
  return <div className={`edge edge-${state.toLowerCase()}`} aria-hidden="true">
    <div className="edge-ring" />
    <div className="edge-mask" />
  </div>;
}
