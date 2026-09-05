import { useRef, useState } from "react";
import type { QAExchange, QAPhase } from "../components/AnswerCard";

/**
 * 文字回答カード（1段目）の中身（2026-09-02、音声読み上げの代わり）。
 * 質問ごとに1件持ち、「続けて聞く」で同じ画面へ積み増す。
 *
 * どの操作も**開いているセッションが無ければ何もしない**。開かないまま
 * サーバーの応答が来ると、成功していてもカードに何も出ない（2026-09-04 実測）。
 */
export type QaCard = {
  exchanges: QAExchange[];
  /** 聞いているだけの状態（質問も答えもまだ無い）。1段目を差し替えない印 */
  listening: boolean;
  open: (question: string, phase: QAPhase) => void;
  append: (question: string, phase: QAPhase) => void;
  update: (patch: Partial<QAExchange>) => void;
  addLines: (lines: string[]) => void;
  addLine: (line: string) => void;
  clear: () => void;
};

export function useQaCard(): QaCard {
  const [exchanges, setExchanges] = useState<QAExchange[]>([]);
  const idRef = useRef(0);

  const open = (question: string, phase: QAPhase) =>
    setExchanges([{ id: ++idRef.current, question, lines: [], phase, startedAt: Date.now() }]);

  const append = (question: string, phase: QAPhase) =>
    setExchanges(prev => [...prev, { id: ++idRef.current, question, lines: [], phase, startedAt: Date.now() }]);

  const update = (patch: Partial<QAExchange>) =>
    setExchanges(prev => {
      if (!prev.length) return prev;
      const next = [...prev];
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });

  const addLines = (lines: string[]) =>
    setExchanges(prev => {
      if (!prev.length || !lines.length) return prev;
      const next = [...prev];
      const last = next[next.length - 1];
      next[next.length - 1] = { ...last, lines: [...last.lines, ...lines] };
      return next;
    });

  // 聞いているあいだは1段目を fastfetch のままにして、呼吸だけ乗せる
  // （本人の指定：聞いている間は上のカードを変えない）。文字回答カードへ
  // 差し替えるのは、聞き取れた質問が入ってから（audio.final で question が
  // 埋まる／拍手起動の固定質問はそこで phase が thinking になる）。
  // セッション自体は WAKING で開いたままにする。ここで作り直すと
  // agent.started などが更新する相手を失う
  const listening = exchanges.length === 1 && exchanges[0].phase === "listening"
    && !exchanges[0].question && !exchanges[0].lines.length;

  return {
    exchanges, listening, open, append, update, addLines,
    addLine: (line: string) => addLines([line]),
    clear: () => setExchanges([]),
  };
}
