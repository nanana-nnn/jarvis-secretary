import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import type { AudioMetrics } from "../audio/types";
import type { SecretaryState } from "../states/types";

type Props = { state: SecretaryState; metricsRef: RefObject<AudioMetrics> };

const ACTIVE_AUDIO = new Set<SecretaryState>(["LISTENING", "TRANSCRIBING"]);

export function PixelCore({ state, metricsRef }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    let frame = 0;
    let smoothed = 0;
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
      const colour = state === "ERROR" || state === "OFFLINE"
        ? style.getPropertyValue("--scheme-error").trim()
        : style.getPropertyValue("--scheme-primary").trim();
      const elapsed = (now - started) / 1000;
      const metrics = metricsRef.current;
      const live = ACTIVE_AUDIO.has(state) ? Math.min(1, metrics.rms * 16) : 0;
      smoothed += (live - smoothed) * (live > smoothed ? .28 : .08);

      let energy = .08 + Math.sin(elapsed * 1.3) * .025;
      if (state === "WAKING") energy = .82 * Math.max(0, 1 - (now - started) / 700);
      else if (state === "LISTENING") energy += smoothed * .95;
      else if (state === "TRANSCRIBING") energy = .24 + Math.sin(elapsed * 8) * .08;
      else if (state === "THINKING") energy = .34 + Math.sin(elapsed * 3.8) * .12;
      else if (state === "SPEAKING") energy = .44 + Math.sin(elapsed * 9) * .18 + Math.sin(elapsed * 4.1) * .1;
      else if (state === "APPROVAL") energy = .25;
      else if (state === "OFFLINE" || state === "ERROR") energy = -.18;

      const columns = 33;
      const rows = 33;
      const cell = Math.min(width / columns, height / rows);
      const gridWidth = cell * columns;
      const gridHeight = cell * rows;
      const offsetX = (width - gridWidth) / 2;
      const offsetY = (height - gridHeight) / 2;
      const high = metrics.hfRatio || 0;
      context.fillStyle = colour || "#1b696f";

      for (let y = 0; y < rows; y += 1) {
        for (let x = 0; x < columns; x += 1) {
          const dx = (x - (columns - 1) / 2) / (columns / 2);
          const dy = (y - (rows - 1) / 2) / (rows / 2);
          const distance = Math.hypot(dx, dy);
          const angle = Math.atan2(dy, dx);
          const voiceRipple = Math.sin(angle * 5 + elapsed * 4) * smoothed * .2;
          const thinkingTrace = state === "THINKING" ? Math.sin(x * .72 + y * .43 + elapsed * 5) * .11 : 0;
          const speakingWave = state === "SPEAKING" ? Math.sin(angle * 8 - elapsed * 10) * .12 : 0;
          const spectralEdge = high * Math.cos(angle * 7) * .09;
          let radius = .34 + energy * .42 + voiceRipple + thinkingTrace + speakingWave + spectralEdge;
          if (state === "APPROVAL") radius += Math.abs(dx) > .08 ? .08 : -.16;
          if (distance <= radius) {
            const inset = Math.max(1, cell * .11);
            const alpha = Math.max(.28, 1 - distance * .38);
            context.globalAlpha = alpha;
            context.fillRect(offsetX + x * cell + inset, offsetY + y * cell + inset, Math.max(1, cell - inset * 2), Math.max(1, cell - inset * 2));
          }
        }
      }
      context.globalAlpha = 1;
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [metricsRef, state]);

  return <canvas ref={canvasRef} className="pixel-core" aria-label="JARVIS 音声反応コア" />;
}
