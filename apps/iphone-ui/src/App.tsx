import { useEffect, useRef, useState, type MouseEvent } from "react";
import { type ClapLog, type ClapSettings } from "./audio/types";
import { AnswerCard } from "./components/AnswerCard";
import { WallpaperPicker, type WallpaperChoice } from "./components/WallpaperPicker";
import { DebugPanel } from "./components/DebugPanel";
import { Ambience } from "./components/Ambience";
import { Fetch } from "./components/Fetch";
import { LavaCore } from "./components/LavaCore";
import { Live, type LiveAction, type LiveFacts } from "./components/Live";
import { SizeProbe } from "./components/SizeProbe";
import { copy } from "./copy";
import { loadClapSettings } from "./clap-settings";
import type { Approval, Telemetry } from "./model";
import { useMicrophone } from "./hooks/useMicrophone";
import { useQaCard } from "./hooks/useQaCard";
import { useSecretarySocket } from "./hooks/useSecretarySocket";
import { useViewportReset } from "./hooks/useViewportReset";
import { transition } from "./states/machine";
import type { SecretaryEvent, SecretaryState } from "./states/types";

// WAKE_ANIM_MS は §15 の手拍子2回の衝撃波と状態遷移を揃える。
// LISTEN_IDLE_MS を過ぎると自分から待機へ戻る（言い忘れたまま起きっぱなしにしない）。
const WAKE_ANIM_MS = 250;
// §6 の表は 8000。9/2 に「話しかけるだけで寝てしまう」として 20000 まで延ばしたが、
// 実際は**タイマーがそもそも張られていなかった**（continueQa で speaking を
// 降ろしておらず、2回目以降は待機へ戻らなかった。2026-09-05 に修正）。
// 直したうえで 10000 にする。話し始めればこのタイマーは止まるので、
// ここが効くのは「起こしたまま何も言わなかった」ときだけ
const LISTEN_IDLE_MS = 10000;
// 文字回答カードを見せたまま自動で待機へ戻すまで（2026-09-02、音声読み上げ廃止）。
// 読み上げと違い「終わった」が音で分からないので、読む時間を見込んで長めにする
const POST_ANSWER_IDLE_MS = 20000;
const HEARD_NOTHING_MS = 5000;     // 「聞き取れませんでした」を見せてから待機へ戻すまで
// 拍手直後、光が縁を1周してから呼吸に切り替わるまで（本人の指定・2026-09-03）。
// style.css の qa-sweep の 1.1s と必ず揃える
const SWEEP_MS = 1100;

export default function App() {
  const [state, setState] = useState<SecretaryState>("BOOTING");
  const [logs, setLogs] = useState<ClapLog[]>([]);
  // 初期値だけ ?debug=1 を見る。以後は state 一本にする（本人の指定・2026-09-04：
  // showDebug を `debug || params?.get("debug")==="1"` の OR にしていたときは、
  // URLに ?debug=1 が付いたままだと CLOSE を押しても閉じられなかった）
  const [debug, setDebug] = useState(() =>
    (import.meta.env.DEV || import.meta.env.VITE_PREVIEW === "1")
    && new URLSearchParams(location.search).get("debug") === "1");
  // 実測値が届くまでの初期値。数字を作らないので、届いていない項目は「…」のままにする
  const [telemetry, setTelemetry] = useState<Telemetry>({
    kernel: "…", uptime: "…", shell: "…", mem: "…", pkgs: 0, user: "…", hname: "…", distro: "…", host: "JARVIS",
  });
  const [settings, setSettings] = useState<ClapSettings>(loadClapSettings);
  // 実測が届くまでは何も点灯させない（分からないものを「動いている」と出さない）
  const [live, setLive] = useState<LiveFacts>({ apps: {}, vault: { tracked: false, dirty: -1 }, phones: 0 });
  // 聞き取り結果の字幕。空文字は「まだ何も無い」を表す（Live 3段目の1行）
  const [caption, setCaption] = useState("");
  // サーバーが発話を検出した。話している間に待機へ戻さないための印
  const [speaking, setSpeaking] = useState(false);
  // 「聞き取れませんでした」を出した時刻。少し見せてから待機へ戻す
  const [heardNothingAt, setHeardNothingAt] = useState(0);
  // 拍手で起きるたびに1つ増える。光の1周（sweep）を撃つ合図に使う
  const [wakeCount, setWakeCount] = useState(0);
  // 壁紙スライダー（2026-09-05）。null なら出さない。
  // applying は「押したがまだ切り替わっていない1枚」。数秒かかるので目印を出す
  const [papers, setPapers] = useState<WallpaperChoice[] | null>(null);
  const [applyingPaper, setApplyingPaper] = useState<string | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  // 「チャット」で開いた打ち込みモード（2026-09-05）。待機へ戻ると閉じる
  const [composing, setComposing] = useState(false);

  const qa = useQaCard();
  const wakeStartedRef = useRef(false);
  // 検出とWSのコールバックは作り直さないので、最新の状態は ref 経由で見る
  const stateRef = useRef(state);
  stateRef.current = state;

  const send = (event: SecretaryEvent) => setState(current => transition(current, event));

  function wakeFromTap(event: MouseEvent<HTMLElement>) {
    if (stateRef.current !== "SLEEP") return;
    const target = event.target;
    if (target instanceof Element && target.closest("button, input, textarea, select, a, label")) return;
    send("TAP_DETECTED");
  }

  const socketRef = useSecretarySocket({
    send, setCaption, setSpeaking, setHeardNothingAt, setPapers, setApplyingPaper,
    setApproval, setLive, setTelemetry,
    qaUpdate: qa.update, qaAddLine: qa.addLine, qaAddLines: qa.addLines,
  });

  const { mic, micStalled, awake, microphone, enable } = useMicrophone(settings, state, {
    // 起こすのは待機中だけ。会話中の物音で状態を飛ばさない
    onClap: () => {
      if (stateRef.current !== "SLEEP") return;
      // 拍手は起こすだけ。何を頼むかは実際に聞いてから判定する
      // （2026-09-02、本人の指定：「手を叩く＝なにする？」ではない。
      // 固定文をその場でCodexへ送っていたのをやめ、WAKING→LISTENING→
      // audio.final という通常の音声経路へ合流させる）
      send("CLAP_DETECTED");
    },
    onLogs: next => {
      setLogs(next);
      const last = next.at(-1);
      if (last) socketRef.current?.send({ type: "clap.candidate", ...last });
    },
    onHealth: report => socketRef.current?.send({ type: "mic.health", ...report }),
    // 送るのは会話中だけ（DESIGN.md §4）。待機中も送っていたため、
    // 考えている20〜40秒のあいだに音声が溜まって接続が切れていた（2026-09-01 実機）
    onAudio: chunk => {
      if (stateRef.current !== "LISTENING") return;
      socketRef.current?.sendAudio(chunk);
    },
  });

  useViewportReset();

  // ?state= / ?debug= / ?wake= の口。dev サーバー、または VITE_PREVIEW=1 で
  // 建てたビルドでだけ開く（実機確認は静的ビルドで行うのでビルドにも要る）。
  const previewable = import.meta.env.DEV || import.meta.env.VITE_PREVIEW === "1";
  const params = previewable ? new URLSearchParams(location.search) : null;

  // **画面が今どう見えているか。** `?state=` は見た目だけを差し替えるので、
  // 「起きているように見えるか」を判定に使うときは state ではなくこちらを見る。
  // 両方を混ぜると、プレビューで押したボタンが直後に打ち消される
  // （2026-09-05、チャットを開いても即座に閉じたのはこれ）
  const preview = params?.get("state")?.toUpperCase() as SecretaryState | undefined;
  const view = preview && preview in copy ? preview : state;

  // ?wake=15 で15秒ごとに手拍子相当を撃つ（プレビュービルドのみ）。
  // 起動→リッスン→待機の一巡を、声も物音も無しに確かめるための口。
  const wakeEvery = Number(params?.get("wake") ?? 0);
  useEffect(() => {
    if (!wakeEvery) return;
    const id = setInterval(() => {
      if (stateRef.current === "SLEEP") send("CLAP_DETECTED");
    }, wakeEvery * 1000);
    return () => clearInterval(id);
  }, [wakeEvery]);

  // 聞き取れなかったときは、文言を5秒見せてから LISTENING へ戻す
  // （DESIGN.md §17 STT_FAILED：「LISTENINGへ戻す」。SLEEPへは落とさない。
  // send("IDLE") で SLEEP まで落としていたため、次の発話を拾えず
  // マイクが録り直されないまま止まっていた（2026-09-04、実機で発見）。
  // STT_FAILED が届いた時点で state は既に LISTENING のまま
  // （AUDIO_FINAL は文字起こしが空でないときしか届かない）ので、
  // ここでは state 遷移を送らず、カードを聞き取り待ちの見た目へ戻すだけでよい
  useEffect(() => {
    if (!heardNothingAt) return;
    const id = setTimeout(() => {
      setHeardNothingAt(0);
      setCaption("なにする？");
      qa.open("", "listening");
    }, HEARD_NOTHING_MS);
    return () => clearTimeout(id);
  }, [heardNothingAt]);

  // 待機へ戻ったら文字回答カードを閉じる。どの経路（ボタン・タイムアウト・
  // エラー復帰）で戻っても、ここで確実に片付ける
  useEffect(() => { if (state === "SLEEP" && qa.exchanges.length) qa.clear(); }, [state, qa.exchanges.length]);
  // 打ち込みモードも待機で畳む（どの経路で戻っても残さない）
  useEffect(() => { if (view === "SLEEP" && composing) setComposing(false); }, [view, composing]);
  // 壁紙スライダーも同じ。どの経路（決定・やめる・エラー復帰）で戻っても畳む
  useEffect(() => {
    if (state === "SLEEP" && papers) { setPapers(null); setApplyingPaper(null); }
  }, [state, papers]);

  // WAKING突入は state だけを見る。speaking を依存に含めていたときは、
  // 拍手の残響などで audio.speaking が一瞬trueになるたびにこのeffectが
  // 再実行され、WAKE_FINISHED を送るはずだった250msタイマーがクリーンアップで
  // 消えていた。wakeStartedRef が既にtrueなので再実行時に新しいタイマーを
  // 張り直さず、AWAKENING のまま二度と進まなくなる（2026-09-04、実機で発見）
  useEffect(() => {
    if (state !== "WAKING") { wakeStartedRef.current = false; return; }
    if (wakeStartedRef.current) return;   // 再描画のたびに再実行されても、起動ごとに一度だけ
    wakeStartedRef.current = true;
    setSpeaking(false);
    setHeardNothingAt(0);
    setWakeCount(n => n + 1);   // 光の1周はこれを合図に撃つ（下の sweeping）
    // カードは LISTENING に入ってから開く（本人の指定：拍手＝「なにする？」
    // ではない。実際に聞いてから走らせる）。質問はまだ無いので空のまま
    qa.open("", "listening");
    const id = setTimeout(() => {
      // 「なにする？」は LISTENING のあいだだけ表示する文言（本人の指定：
      // それ以外で出ると意味が通らない）。聞き取れたら audio.final が
      // 本物の文で上書きする。何も聞けなければ下の IDLE 側で消す
      setCaption("なにする？");
      send("WAKE_FINISHED");
    }, WAKE_ANIM_MS);
    return () => clearTimeout(id);
  }, [state]);

  useEffect(() => {
    if (state === "LISTENING") {
      // 話し始めていたら待機へ戻さない。言い終わるまで待つ
      // （終端は VAD が決める。長すぎる発話は §6 の 30秒で必ず切れる）
      if (speaking) return;
      const id = setTimeout(() => { setCaption(""); send("IDLE"); }, LISTEN_IDLE_MS);
      return () => clearTimeout(id);
    }
    // 文字回答カードを見せたまま自動で待機へ戻す（読み上げ廃止・2026-09-02）。
    // 「戻る」「続けて聞く」のどちらかを押せばこのタイマーは次の描画で消える
    if (state === "SPEAKING") {
      // 壁紙スライダーを開けている間は寝かせない。75枚を選ぶのに
      // POST_ANSWER_IDLE_MS(20秒)では足りず、選んでいる最中に消える
      if (papers) return;
      const id = setTimeout(() => { qa.clear(); send("IDLE"); }, POST_ANSWER_IDLE_MS);
      return () => clearTimeout(id);
    }
    if (state === "ERROR") {
      const id = setTimeout(() => send("RETRY"), 5000);
      return () => clearTimeout(id);
    }
  }, [state, speaking, papers]);

  async function enableMic() {
    // タップ自体が届いているかを切り分けるための即時マーカー
    // （2026-09-02、「押しても何も出ない」の原因調査）
    setCaption("ENABLE MIC を押しました…");
    const result = await enable();
    if (result.ok) return;
    // 何が失敗したか画面に出す。「押しても何も起きない」の原因切り分けに要る
    setCaption(`マイクを開始できません: ${result.detail}`);
    send("SYSTEM_ERROR");
  }

  /**
   * 打ち込んだ文を Codex へ送る（2026-09-05）。
   *
   * **声とまったく同じ経路に乗せる。** サーバーの `text.input` はルーターを
   * 通るので、判定はサーバー1か所のまま（画面側に2つ目の判定を作らない）。
   * 状態も声のときと同じ道を辿らせる：SPEAKING にいたら LISTENING へ戻し、
   * そこから AUDIO_FINAL で TRANSCRIBING へ入れる。飛ばすと THINKING の
   * 見た目にならず、経過も出ない
   */
  function sendChat(text: string) {
    const value = text.trim();
    if (!value) return;
    if (qa.exchanges.length) qa.append(value, "thinking");
    else qa.open(value, "thinking");
    setCaption(value);
    send("CONTINUE");     // SPEAKING → LISTENING（他の状態では何も起きない）
    send("AUDIO_FINAL");  // LISTENING → TRANSCRIBING（声と同じ入口）
    socketRef.current?.send({ type: "text.input", text: value });
  }

  // 「戻る」：カードを閉じて待機へ。「続けて聞く」：カードは残したまま
  // 次の発話を録る（WAKING を経由しない）
  function closeQa() { qa.clear(); setComposing(false); send("IDLE"); }
  function continueQa() {
    qa.append("", "listening");
    setCaption("なにする？");   // 起動直後と同じく LISTENING のあいだだけ出す
    // **前の発話の speaking を必ず降ろす。** これを忘れると、下の無操作タイマーが
    // `if (speaking) return` に落ちて張られず、LISTENING から自力で待機へ戻れなくなる。
    // 「続けて聞く」は WAKING を通らないので、あちらの setSpeaking(false) は効かない
    // （2026-09-05 に発見。分割前から同じ。「listening が長すぎる」の正体）
    setSpeaking(false);
    send("CONTINUE");
  }

  async function decideApproval(approve: boolean) {
    if (!approval) return;
    const current = approval;
    try {
      const response = await fetch(`/jobs/${encodeURIComponent(current.id)}/${approve ? "approve" : "reject"}`, { method: "POST" });
      const result = await response.json() as { summary?: string; spoken_reply?: string };
      if (!response.ok) throw new Error(typeof result.summary === "string" ? result.summary : "APPROVAL FAILED");
      setApproval(null);
      const summary = typeof result.summary === "string" && result.summary ? result.summary
        : typeof result.spoken_reply === "string" ? result.spoken_reply : "CHANGE REVIEW COMPLETE";
      setCaption(summary);
      qa.addLines(summary.split("\n").map(line => line.trim()).filter(Boolean));
      qa.update({ phase: "done" });
      send("AGENT_COMPLETED");
    } catch (error) {
      const message = error instanceof Error ? error.message : "APPROVAL FAILED";
      setCaption(message);
      qa.addLine(message);
      qa.update({ phase: "done" });
      send("SYSTEM_ERROR");
    }
  }

  // 「光が縁を1周」は**拍手で起きた合図**（本人の指定・2026-09-03）。
  // 依存を wakeCount にする。listening の false→true で撃つと、聞き取り直し
  // （STT_FAILED後の再リッスン・「続けて聞く」）のたびに回り直して
  // 「ずっと回っている」ように見える（2026-09-04 実機）。
  // また state を依存にすると、WAKING→LISTENING の遷移(250ms)で
  // クリーンアップが走り SWEEP_MS(1100ms)のタイマーが消えて回りっぱなしになる。
  // 起動ごとに1つ増える wakeCount なら、その間に state が動いても消えない
  const [sweeping, setSweeping] = useState(false);
  useEffect(() => {
    if (!wakeCount) return;
    setSweeping(true);
    const id = setTimeout(() => setSweeping(false), SWEEP_MS);
    return () => clearTimeout(id);
  }, [wakeCount]);

  // 起きているあいだだけ操作ボタンを出す（2026-09-05、本人の指定）。
  // **待機へ戻ると消える。** 押してやることは、どれも既にある経路に乗せる
  // （壁紙とタスクは発話と同じ text.input を通すので、判定はサーバーの
  //  ルーター1か所のまま。画面側に2つ目の判定を作らない）
  const ask = (text: string) => {
    qa.open(text, "thinking");
    socketRef.current?.send({ type: "text.input", text });
  };
  const actions: LiveAction[] = [
    { key: "paper", icon: "\u{f02e9}", label: "背景", onPress: () => ask("壁紙かえたい") },
    // **チャットは打ち込む口を開く。** 声で頼めない場面（人の前・静かな所）でも
    // Codex へ通せるようにする。押しただけでは何も送らない
    { key: "chat", icon: "\u{f0b79}", label: "チャット", onPress: () => setComposing(true) },
    { key: "tasks", icon: "\uf0ae", label: "タスク", onPress: () => ask("今日のタスクは？") },
    { key: "sleep", icon: "\u{f0904}", label: "待機", onPress: closeQa },
  ];

  const content = copy[view];
  const connected = !["BOOTING", "OFFLINE", "ERROR"].includes(view);
  // 待機・起動中・切断中は操作ボタンを出さない（押しても通らない状態のため）
  const awakeNow = !["SLEEP", "BOOTING", "OFFLINE"].includes(view);
  const showDebug = debug;

  // sysmon の右列と同じ3段。上から fetch / dots / 状態（tty-clock の位置）。
  // 質問が始まったら1段目を文字回答カードへ差し替える（読み上げ廃止・2026-09-02）
  return <main className={`shell state-${view.toLowerCase()}`} onClick={wakeFromTap}>
    <Ambience state={view} />
    {/* 1段目は3通りに差し替わる。**枠の大きさはどれも同じ**（grid の
        minmax(0,1fr) の段をそのまま使う。中身だけが変わる）。
        壁紙スライダーが最優先（出している間は他の表示に邪魔させない） */}
    {papers
      ? <WallpaperPicker items={papers} applying={applyingPaper}
          onPick={id => {
            setApplyingPaper(id);
            socketRef.current?.send({ type: "wallpaper.select", id });
          }}
          onCancel={() => { setPapers(null); setApplyingPaper(null); setCaption(""); send("IDLE"); }} />
      : composing || (qa.exchanges.length && !qa.listening)
      ? <AnswerCard exchanges={qa.exchanges} onBack={closeQa} onContinue={continueQa}
          obsidianActive={Boolean(live.apps.obsidian?.alive)}
          onSend={composing ? sendChat : undefined} />
      : <Fetch facts={telemetry} link={connected ? "LINKED" : "OFFLINE"} glow={qa.listening} sweep={sweeping}
          wake={logs} />}

    <section className="core-stage panel">
      <LavaCore state={view} />
    </section>

    <Live state={content.en} code={content.code} live={live} caption={caption}
      actions={awakeNow ? actions : undefined} />

    {approval ? <section className="approval panel" aria-live="polite">
      <div>REVIEW CHANGES</div>
      {approval.warnings.map(line => <p className="approval-warning" key={line}>! {line}</p>)}
      <p>{approval.summary}</p>
      <code>{approval.files.join("\n")}</code>
      <pre>{approval.diff}</pre>
      <div className="approval-actions">
        <button className="primary-action" onClick={() => { void decideApproval(true); }}>APPROVE</button>
        <button className="warning-action" onClick={() => { void decideApproval(false); }}>REJECT</button>
      </div>
    </section> : null}

    <footer className="controls">
      <div className="system-flags">
        {/* "VAULT 5" という固定値がずっと出ていた。飾りで、実測ではなかった
            （2026-09-01、実機の表示とPCのgit statusが食い違って発覚）。
            Live.tsx の live-meta に同じ実測を出す仕組みが既にあるので、
            ここもそれへ合わせる。「点灯はすべてサーバーの実測」の原則どおり */}
        <span>VAULT {!live.vault.tracked ? "?" : live.vault.dirty < 0 ? "?" : live.vault.dirty}</span>
        <span>LAN SECURE</span><span>NO CLOUD</span>
        {mic === "on" ? <span>{awake ? "SCREEN ON" : "SCREEN LOCKS"}</span> : null}
      </div>
      <div className="actions">
          {mic !== "on"
            ? <button className="primary-action" onClick={enableMic}>ENABLE MIC</button>
            : <span className="mic-live">● MIC LIVE</span>}
          {mic === "denied" ? <span className="warning">MIC DENIED</span> : null}
          {micStalled ? <button className="warning-action" onClick={() => { void microphone.ensureRunning(); }}>TAP TO RESUME MIC</button> : null}
          <button className="debug-action" onClick={() => setDebug(value => !value)} aria-label="DEBUG LOG">•••</button>
      </div>
    </footer>
    {showDebug ? <DebugPanel logs={logs} settings={settings} onSettings={setSettings} onClose={() => setDebug(false)}
        onSend={value => {
          // 拍手を経由しないので、qa をここで自分で開く。開かないまま送ると
          // agent.started/completed が update/addLines の
          // 「開いているセッションが無ければ何もしない」ガードに落ちて、
          // サーバーは成功していてもカードに何も出ない（2026-09-04、実測）
          qa.open(value, "thinking");
          socketRef.current?.send({ type: "text.input", text: value });
        }} /> : null}
    {/* ホーム画面 PWA では start_url が "/" なので ?size=1 が届かない。
        崩れるのが standalone のときだけなので、DEBUG からも出す */}
    {showDebug || params?.get("size") === "1" ? <SizeProbe /> : null}
  </main>;
}
