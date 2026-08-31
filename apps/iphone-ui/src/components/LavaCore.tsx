import { useEffect, useRef } from "react";
import type { SecretaryState } from "../states/types";

type Props = { state: SecretaryState };

/**
 * CachyOS の sysmon「dots」パネルの移植。
 *
 * 実物は `~/.config/caelestia/sysmon-watch.sh dots` が起動する **lavat**
 * （`lavat -g -c 615a7a -k 615a7a`）で、sysmon-dots.py ではない。
 * lavat が入っていない環境向けのフォールバックが sysmon-dots.py なので、
 * DESIGN.md §15.1 が移植先として挙げていたのは実際には画面に出ていない方だった。
 *
 * lavat はメタボールのラバライトで、音には一切反応せず常に動き続ける。
 * 値はすべて lavat.c v3.0.0 の既定値そのまま（下のコメントに対応箇所を書いた）。
 */

// lavat.c: maxX = tb_width(), maxY = tb_height() * 2
// 縦が2倍なのは ▀ ▄ の半ブロックで1行を上下2ピクセルとして描くため。
//
// 本物は端末の実寸からグリッドを決めるので、ここも**キャンバスの実寸から決める**。
// 列数は実機の dots パネル(620x340px / 1ピクセル 9x10px)と同じ 69 に固定し、
// 行数は「1ピクセルが 9:10 になる数」を面の縦横比から出す。
// 固定の 69x34 にすると、パネルが実物と違う形のとき letterbox の隙間が出る
// （2026-08-31、2段目の上に 10px の隙間、下が 23px 切れていた）。
const COLS = 69;
const CELL_ASPECT = 9 / 10;   // 1ピクセルの 横:縦

function rowsFor(width: number, height: number): number {
  return Math.max(8, Math.round(COLS * (height / width) * CELL_ASPECT));
}

const NBALLS = 10;        // lavat.c: static int nballs = 10
const RADIUS_IN = 110;    // lavat.c: static float radiusIn = 110
const SUM_CONST = 0.0225; // lavat.c: sumConst = 0.0225

// lavat.c: radius = (radiusIn * radiusIn + (float)(maxX * maxY)) / 15000
// グリッドが可変になったので、行数が変わるたびに計算し直す
function radiusSqFor(rows: number): number {
  const radius = (RADIUS_IN * RADIUS_IN + COLS * rows) / 15000;
  return radius * radius;
}

// lavat.c: speedMult = 11 - speedMult （既定の 5 から 6 になる）
//          speed = (((1 / (float)(maxX + maxY)) * 1000000) + 10000) * speedMult  [µs]
// 実物はこの間隔でしか更新しないので、なめらかにせずカクつきごと再現する。
const SPEED_MULT = 11 - 5;
function frameMsFor(rows: number): number {
  return ((1 / (COLS + rows)) * 1_000_000 + 10_000) * SPEED_MULT / 1000;
}

type Ball = { x: number; y: number; vx: number; vy: number };

// lavat.c init_params(): x,y は一様乱数、vx,vy は ±1.0（margin は -C 未指定なので 0）
function createBalls(rows: number): Ball[] {
  return Array.from({ length: NBALLS }, () => ({
    x: Math.floor(Math.random() * COLS),
    y: Math.floor(Math.random() * rows),
    vx: Math.random() < 0.5 ? -1 : 1,
    vy: Math.random() < 0.5 ? -1 : 1,
  }));
}

// lavat.c の移動処理から gravityMode 分岐（-G 未指定なので通らない）を除いたもの
function step(balls: Ball[], rows: number): void {
  const maxXf = COLS - 1;
  const maxYf = rows - 1;
  for (const ball of balls) {
    const nextX = ball.x + ball.vx;
    const nextY = ball.y + ball.vy;

    if (ball.vy > 2.5) ball.vy = 2.5;
    if (ball.vy < -2.5) ball.vy = -2.5;

    if (nextX > maxXf) { ball.x = maxXf; ball.vx = -ball.vx; }
    else if (nextX < 0) { ball.x = 0; ball.vx = -ball.vx; }
    else ball.x = nextX;

    if (nextY > maxYf) { ball.y = maxYf; ball.vy = -Math.abs(ball.vy); }
    else if (nextY < 0) { ball.y = 0; ball.vy = Math.abs(ball.vy); }
    else ball.y = nextY;

    if (Math.abs(ball.vx) < 0.15) ball.vx = ball.vx < 0 ? -0.15 : 0.15;
  }
}

export function LavaCore({ state }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // 色だけは状態で変えるが、そのために描画ループを作り直さない。
  // 依存配列に state を入れると、状態が変わるたびに玉が作り直されて
  // 指パッチンのたびに絵が飛ぶ（2026-08-31、実際そうなっていた）。
  // lavat は何にも反応せず動き続けるものなので、ここは切り離す。
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    // 面の実寸が決まるまで行数は出せないので、最初の描画で確定させる
    let rows = 0;
    let balls: Ball[] = [];
    let radiusSq = 0;
    let frameMs = 0;
    let frame = 0;
    let last = performance.now();

    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);

      const bounds = canvas.getBoundingClientRect();
      if (bounds.width < 1 || bounds.height < 1) return;
      const scale = Math.min(devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.round(bounds.width * scale));
      const height = Math.max(1, Math.round(bounds.height * scale));

      // 面の形が変わったらグリッドを組み直す（回転・ツールバーの出入りなど）。
      // 玉は作り直さず、新しい行数へ収まるように詰めるだけにする
      const wanted = rowsFor(bounds.width, bounds.height);
      if (wanted !== rows) {
        const previous = rows;
        rows = wanted;
        radiusSq = radiusSqFor(rows);
        frameMs = frameMsFor(rows);
        if (!balls.length) balls = createBalls(rows);
        else if (previous > 0) {
          const ratio = rows / previous;
          for (const ball of balls) ball.y = Math.min(rows - 1, ball.y * ratio);
        }
      }

      // 実物と同じ更新間隔まで描かない（rAF の 60fps では回さない）
      if (now - last < frameMs) return;
      last = now;
      step(balls, rows);

      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      context.clearRect(0, 0, width, height);

      const style = getComputedStyle(document.documentElement);
      // -c と -k に同じ色を渡しているのでグラデーションにならず単色で塗られる
      const view = stateRef.current;
      context.fillStyle = (view === "ERROR" || view === "OFFLINE"
        ? style.getPropertyValue("--scheme-error").trim()
        : style.getPropertyValue("--scheme-primary").trim()) || "#1b696f";

      // lavat.c の render ループ。sum が閾値を超えたセルを塗る。
      // 隙間を空けずに敷き詰める（実物は █ の連続なので境界に隙間がない）
      const cellW = width / COLS;
      const cellH = height / rows;
      for (let i = 0; i < COLS; i += 1) {
        for (let y = 0; y < rows; y += 1) {
          let sum = 0;
          for (const ball of balls) {
            const dx = i - ball.x;
            const dy = y - ball.y;
            const distSq = dx * dx + dy * dy;
            sum += distSq === 0 ? Number.MAX_VALUE : radiusSq / distSq;
          }
          if (sum > SUM_CONST) {
            context.fillRect(
              Math.floor(i * cellW), Math.floor(y * cellH),
              Math.ceil(cellW), Math.ceil(cellH),
            );
          }
        }
      }
    };

    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, []);   // ← 状態を入れないこと。入れるとシミュレーションが作り直される

  return <canvas ref={canvasRef} className="lava-core" aria-hidden="true" />;
}
