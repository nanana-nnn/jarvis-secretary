import { useEffect, useRef } from "react";
import type { SecretaryState } from "../states/types";

type Props = { state: SecretaryState; getBands: () => Float32Array | null };

const BAR_COUNT = 20; // sysmon-dots.py の cava 設定 BARS=20 に合わせる
const GRID = 33;

function hexToRgb(hex: string): [number, number, number] {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) return [27, 105, 111];
  const value = parseInt(match[1], 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/**
 * DESIGN.md §15.1 の移植対象: ~/.config/caelestia/sysmon-dots.py。
 * 中心からの極座標へ変換し、|dx| をバー番号へ割り当てて左右対称にする（元コードのまま）。
 * 半径は同じ `0.30 + level * 0.72`。単一 rms で円を拡大縮小するだけの実装はしない。
 * 元の端末描画と同じく、塗りは単色フラット（距離によるフェードは付けない）。
 */
export function PixelCore({ state, getBands }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const bands = useRef(new Float32Array(BAR_COUNT));
  const avgLevel = useRef(0);
  const hit = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    let frame = 0;
    const started = performance.now();

    const draw = (now: number) => {
      const bounds = canvas.getBoundingClientRect();
      const scale = Math.min(devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.round(bounds.width * scale));
      const height = Math.max(1, Math.round(bounds.height * scale));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      context.clearRect(0, 0, width, height);

      const style = getComputedStyle(document.documentElement);
      const baseColour = state === "ERROR" || state === "OFFLINE"
        ? style.getPropertyValue("--scheme-error").trim()
        : style.getPropertyValue("--scheme-primary").trim();
      const highlightColour = style.getPropertyValue("--scheme-on-primary").trim();
      const elapsed = (now - started) / 1000;

      // PCのcava（本物のsysmon dotsと同じ音源）を最優先で読む。届いていない間だけ
      // マイク・帯域ごとに位相をずらした疑似値へ落ちる（単一値で円を拡大縮小にしない）
      const live = getBands();
      for (let i = 0; i < BAR_COUNT; i += 1) {
        const target = live ? live[i] : 0.12 + 0.10 * Math.sin(elapsed * (1.1 + i * 0.19) + i);
        const current = bands.current[i];
        bands.current[i] = current + (target - current) * (target > current ? 0.35 : 0.12);
      }

      // 反応すると色を変える: 直近の平均音量よりはっきり跳ねた瞬間だけハイライト色を混ぜ、
      // 指数的に元の色へ戻す（sysmon-dots.py 自体には無い演出だが、常時反応がひと目でわかる）
      let overall = 0;
      for (let i = 0; i < BAR_COUNT; i += 1) overall += bands.current[i];
      overall /= BAR_COUNT;
      avgLevel.current += (overall - avgLevel.current) * 0.02;
      if (overall > avgLevel.current * 1.6 + 0.06) hit.current = 1;
      else hit.current *= 0.90;

      let boost = 0;
      if (state === "WAKING") boost = 0.55 * Math.max(0, 1 - (now - started) / 700);
      else if (state === "THINKING") boost = 0.14 + Math.sin(elapsed * 3.8) * 0.06;
      else if (state === "SPEAKING") boost = 0.18 + Math.sin(elapsed * 9) * 0.08;
      else if (state === "APPROVAL") boost = 0.1;
      else if (state === "OFFLINE" || state === "ERROR") boost = -0.14;

      const base = hexToRgb(baseColour || "#1b696f");
      const highlight = hexToRgb(highlightColour || "#e8fdff");
      const mix = Math.min(1, hit.current);
      const r = Math.round(base[0] + (highlight[0] - base[0]) * mix);
      const g = Math.round(base[1] + (highlight[1] - base[1]) * mix);
      const b = Math.round(base[2] + (highlight[2] - base[2]) * mix);
      context.fillStyle = `rgb(${r}, ${g}, ${b})`;

      const cell = Math.min(width, height) / GRID;
      const gridSize = cell * GRID;
      const offsetX = (width - gridSize) / 2;
      const offsetY = (height - gridSize) / 2;
      const centre = (GRID - 1) / 2;

      for (let y = 0; y < GRID; y += 1) {
        const dy = (y - centre) / centre;
        for (let x = 0; x < GRID; x += 1) {
          const dx = (x - centre) / centre;
          const dist = Math.hypot(dx, dy);
          const ang = Math.abs(dx);
          const t = dist > 0 ? ang / dist : 0;
          const idx = Math.min(BAR_COUNT - 1, Math.floor(t * (BAR_COUNT - 1)));
          const level = Math.min(1, Math.max(0, bands.current[idx] + boost));
          const radius = 0.30 + level * 0.72;
          if (dist <= radius) {
            const inset = Math.max(1, cell * .11);
            context.fillRect(offsetX + x * cell + inset, offsetY + y * cell + inset, Math.max(1, cell - inset * 2), Math.max(1, cell - inset * 2));
          }
        }
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [getBands, state]);

  return <canvas ref={canvasRef} className="pixel-core" aria-label="JARVIS voice-reactive core" />;
}
