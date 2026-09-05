import { useEffect, useRef, useState } from "react";

/**
 * 1段目（旧 fastfetch カード）を、質問中だけ差し替えるターミナル風の応答カード。
 * DESIGN.md「次の実装：文字回答カード（2026-09-02 合意）」の実装。
 *
 * 音声読み上げを廃止した代わり。答えは喋らず、ここへ流し込む。
 * プロンプト行は本人の `~/.config/starship.toml` の2行と同じ構成にする
 * （本人の指定：「このパソコンのターミナルと同じにして」）。
 *   1行目: cmd_duration（黄・時計アイコン+経過秒） directory（~ ＋ シアンのバッジ）
 *   2行目: character（青の • ＋ 白の ▶）に続けて質問文
 * `cmd_duration` は経過秒を実測で出す（待っているあいだ実際に time をtickさせる。
 * 本物のターミナルは完了後にしか出さないが、待ち時間が分かるほうが実用的なので
 * ここでは進行中も動かす）。`directory` に本物のパスは無いので "vault" と表示する
 * （Vault を相手にしている、という点は嘘ではない）。
 */

export type QAPhase = "listening" | "thinking" | "streaming" | "done";
export type QAExchange = { id: number; question: string; lines: string[]; phase: QAPhase; startedAt: number };

const AUTO_FOLLOW_THRESHOLD_PX = 24;

/**
 * `onSend` を渡すと、下に打ち込み欄が出る（2026-09-05、本人の指定「チャット」）。
 * **浮かせた窓は作らない。** 質問と回答が積み上がるこのカードが既にチャットなので、
 * ここへ口を足すだけにする。窓を浮かせると、どの段も同じ枠という前提から外れ、
 * iOS standalone の位置ズレ（2026-09-02、101px）を踏み直すことになる。
 *
 * 打ち込んだ文は声と同じ経路（サーバーの `text.input` → ルーター → Codex）へ流す。
 * 画面側に2つ目の判定を作らない。
 */
export function AnswerCard(
  { exchanges, onBack, onContinue, obsidianActive, onSend }:
  { exchanges: QAExchange[]; onBack: () => void; onContinue: () => void;
    obsidianActive: boolean; onSend?: (text: string) => void },
) {
  const [draft, setDraft] = useState("");
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

  // cmd_duration を動かすための1秒ティック。完了したら止める（もう変わらないため）
  const [, forceTick] = useState(0);
  useEffect(() => {
    if (done) return;
    const id = window.setInterval(() => forceTick(t => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [done]);

  return <section className={`fetch panel qa-card card-glow ${done ? "glow-idle" : "glow-active"} ${obsidianActive ? "glow-obsidian" : ""}`}>
    <div className="qa-scroll" ref={scrollRef} onScroll={handleScroll}>
      {exchanges.map(exchange => {
        const elapsed = Math.max(0, Math.round((Date.now() - exchange.startedAt) / 1000));
        return <div className="qa-exchange" key={exchange.id}>
          <p className="qa-meta">
            <span className="qa-duration"><i>󰪢</i> {elapsed}s</span>
            <span className="qa-dir">~ <b>vault</b></span>
          </p>
          <p className="qa-prompt">
            <span className="qa-sep">•</span> <span className="qa-badge">▶</span> {exchange.question || "…"}
          </p>
          {exchange.lines.map((line, i) => <p className="qa-line" key={i}>{line}</p>)}
          {exchange.phase !== "done" ? <span className="qa-cursor" aria-hidden="true">█</span> : null}
        </div>;
      })}
    </div>
    {onSend ? <form className="qa-compose" onSubmit={event => {
      event.preventDefault();
      const text = draft.trim();
      if (!text) return;
      setDraft("");
      onSend(text);
    }}>
      {/* プロンプト行と同じ字を頭に置いて、打つ場所だと分かるようにする */}
      <span className="qa-badge" aria-hidden="true">▶</span>
      <input value={draft} onChange={event => setDraft(event.target.value)}
             placeholder="なにする？" aria-label="Codex への指示"
             enterKeyHint="send" autoComplete="off" autoCorrect="off" />
      <button type="submit" className="primary-action" disabled={!draft.trim()}>送る</button>
    </form> : null}
    {done ? <div className="qa-actions">
      <button className="qa-back" onClick={onBack}>戻る</button>
      <button className="qa-continue primary-action" onClick={onContinue}>続けて聞く</button>
    </div> : null}
  </section>;
}
