import { useEffect, useRef } from "react";

/**
 * 1段目（旧 fastfetch カード）を、質問中だけ差し替えるターミナル風の応答カード。
 * DESIGN.md「次の実装：文字回答カード（2026-09-02 合意）」の実装。
 *
 * 音声読み上げを廃止した代わり。答えは喋らず、ここへ流し込む。
 * `› 質問文` → 点滅カーソル → 回答を行単位で追加表示 → 完了で「戻る」「続けて聞く」。
 */

export type QAPhase = "listening" | "thinking" | "streaming" | "done";
export type QAExchange = { id: number; question: string; lines: string[]; phase: QAPhase };

const AUTO_FOLLOW_THRESHOLD_PX = 24;

export function AnswerCard(
  { exchanges, onBack, onContinue }:
  { exchanges: QAExchange[]; onBack: () => void; onContinue: () => void },
) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // 利用者が上へスクロールしたら自動追従を止める（DESIGN.md）。
  // 新しい発話が始まったら（exchanges の件数が増えたら）また追従に戻す
  const autoFollow = useRef(true);
  const exchangeCount = exchanges.length;

  useEffect(() => { autoFollow.current = true; }, [exchangeCount]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !autoFollow.current) return;
    el.scrollTop = el.scrollHeight;
  });

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom > AUTO_FOLLOW_THRESHOLD_PX) autoFollow.current = false;
  };

  const last = exchanges.at(-1);
  const done = last ? last.phase === "done" : false;

  return <section className={`fetch panel qa-card ${done ? "qa-idle" : "qa-active"}`}>
    <div className="qa-scroll" ref={scrollRef} onScroll={handleScroll}>
      {exchanges.map(exchange => <div className="qa-exchange" key={exchange.id}>
        <p className="qa-prompt">
          <span className="qa-badge">▶</span> {exchange.question || "…"}
        </p>
        {exchange.lines.map((line, i) => <p className="qa-line" key={i}>{line}</p>)}
        {exchange.phase !== "done" ? <span className="qa-cursor" aria-hidden="true">█</span> : null}
      </div>)}
    </div>
    {done ? <div className="qa-actions">
      <button className="qa-back" onClick={onBack}>戻る</button>
      <button className="qa-continue primary-action" onClick={onContinue}>続けて聞く</button>
    </div> : null}
  </section>;
}
