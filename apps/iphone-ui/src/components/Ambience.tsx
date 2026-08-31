import { useEffect, useRef, useState } from "react";
import type { SecretaryState } from "../states/types";

// 起動演出の長さ。状態機械の WAKING 滞在（WAKE_ANIM_MS = 250ms）より長い。
// 状態の滞在時間に演出を縛ると途中で切れるので、入った瞬間を拾って
// ここで測り切る（2026-08-31、1.1秒の演出が 250ms で切れていた）。
const BURST_MS = 1400;

/**
 * 画面全体の空気（待機時の減光・全面の発光・縁を回る光）。
 *
 * ただ光らせると、2段目のドットと同じ「情報量ゼロの面積」が増えるだけなので、
 * **光り方は必ず状態に紐づける**。視界の端だけで状態が分かるのが狙い。
 *
 *   SLEEP        … 全体を少し落とし、細い光がゆっくり一周する（常設で眩しくしない）
 *   WAKING       … 減光を外し、縁を太く焚いて一周＋全面が発光する（ここは派手に）
 *   LISTENING    … 明るいまま保つ
 *   THINKING 他  … 速く脈打つ
 *   ERROR/OFFLINE… 形は変えず色だけ error へ寄せる
 *
 * 発光の作り方は ~/dev/hyper のニュース動画から取った（推測せず実物を読んだ）。
 * あちらは `#glow-a` / `#glow-b` という大きな面を `filter: blur(140px)` でぼかし、
 * 低い不透明度で隅に置いてゆっくり拡縮させている。色の入れ替えも 0.8 秒の
 * ease で滑らせていたので、こちらの transition もその時間に合わせた。
 *
 * 待機時に落とすのは演出だけが理由ではない。DESIGN.md §15 の
 * 「待機時は輝度を落とす / 真っ白な静止画を長時間・最大輝度で出さない」に沿う。
 *
 * 要素構成（すべて CSS で動く。JS からは class を替えるだけ）:
 *   blob  … 全面の発光。対角に2枚置いて呼吸させる
 *   ring  … 縁を回る光。conic-gradient を transform で回す
 *   mask  … ring の内側を背景色で隠して、縁だけ残す
 *   scrim … 待機時の減光。テーマ色を薄く敷くので light/dark どちらでも濁らない
 *
 * `@property` は iOS Safari 16.4 未満で効かないので使わない。
 * この要素の祖先に filter を掛けないこと（position: fixed が壊れる）。
 */
export function Ambience({ state }: { state: SecretaryState }) {
  const [bursting, setBursting] = useState(false);
  // null 始まりにして、最初の描画が WAKING でも「入った」と見なす
  // （?state=WAKING の見た目確認でも演出が出るように）
  const previous = useRef<SecretaryState | null>(null);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const entered = previous.current !== "WAKING" && state === "WAKING";
    previous.current = state;
    if (!entered) return;
    setBursting(true);
    // タイマーは effect のクリーンアップで消さない。
    // WAKING の滞在は 250ms しかないので、次の状態へ移った時点で
    // クリーンアップが走り、消灯用の setBursting(false) が永久に来なくなる。
    // その結果 amb-waking が固定され、待機へ戻っても光ったまま・暗さも戻らない
    // （2026-08-31、実機でその状態になっていた）。
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setBursting(false), BURST_MS);
  }, [state]);

  // 片付けるのは本当に消えるときだけ
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  // 起動演出中は状態が先へ進んでも burst を続ける。key で animation を必ず巻き戻す
  const tone = bursting ? "waking" : state.toLowerCase();
  return <div className={`amb amb-${tone}`} aria-hidden="true">
    <div className="amb-blob amb-blob-a" key={`a-${bursting}`} />
    <div className="amb-blob amb-blob-b" key={`b-${bursting}`} />
    <div className="amb-ring" key={`r-${bursting}`} />
    <div className="amb-mask" />
    <div className="amb-scrim" />
  </div>;
}
