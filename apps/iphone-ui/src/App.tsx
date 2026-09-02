import { useEffect, useMemo, useRef, useState } from "react";
import { ReconnectingSocket, type SocketStatus } from "./api/socket";
import { ClapDetector } from "./audio/clap-detector";
import { ClapMicrophone } from "./audio/microphone";
import { ScreenWakeLock } from "./audio/wake-lock";
import { DEFAULT_CLAP_SETTINGS, type ClapLog, type ClapSettings } from "./audio/types";
import { AnswerCard, type QAExchange, type QAPhase } from "./components/AnswerCard";
import { DebugPanel } from "./components/DebugPanel";
import { Ambience } from "./components/Ambience";
import { Fetch, type Facts } from "./components/Fetch";
import { LavaCore } from "./components/LavaCore";
import { Live, type LiveFacts } from "./components/Live";
import { SizeProbe } from "./components/SizeProbe";
import { transition } from "./states/machine";
import type { SecretaryEvent, SecretaryState } from "./states/types";

// WAKE_ANIM_MS は §15 の手拍子2回の衝撃波と状態遷移を揃える。
// LISTEN_IDLE_MS を過ぎると自分から待機へ戻る（言い忘れたまま起きっぱなしにしない）。
const WAKE_ANIM_MS = 250;
// §6 の表は 8000。実機だと話しかけるだけで寝てしまい短すぎたので延ばしてある。
// あわせて、話し始めたらこのタイマーは止める（下の speaking）
const LISTEN_IDLE_MS = 20000;
// 文字回答カードを見せたまま自動で待機へ戻すまで（2026-09-02、音声読み上げ廃止）。
// 読み上げと違い「終わった」が音で分からないので、読む時間を見込んで長めにする
const POST_ANSWER_IDLE_MS = 20000;
const SNAP_TAIL_MS = 450;          // 拍手の余韻が消えるまで録音を待つ
const HEARD_NOTHING_MS = 5000;     // 「聞き取れませんでした」を見せてから待機へ戻すまで

// サーバーから来る差し色を検査する。信頼せずに形だけ見る。
const HEX = /^#[0-9a-f]{6}$/i;

type Telemetry = Facts & { host: string };
type Scheme = {
  mode: "light" | "dark";
  background: string;
  surfaceContainer: string;
  surfaceContainerHigh: string;
  onSurface: string;
  onSurfaceVariant: string;
  outlineVariant: string;
  primary: string;
  onPrimary: string;
  error: string;
};

const schemeVariables: Record<Exclude<keyof Scheme, "mode">, string> = {
  background: "--scheme-bg",
  surfaceContainer: "--scheme-surface",
  surfaceContainerHigh: "--scheme-surface-high",
  onSurface: "--scheme-text",
  onSurfaceVariant: "--scheme-muted",
  outlineVariant: "--scheme-outline",
  primary: "--scheme-primary",
  onPrimary: "--scheme-on-primary",
  error: "--scheme-error",
};

/**
 * 状態ごとの表示文。DESIGN.md §15.1: 画面上の文字はすべて英語、短い状態名だけにする。
 * code は状態の系統が一目で分かるよう接頭辞を揃えてある（SYS / COM / AI / SEC / ERR / NET）。
 */
type StateCopy = { en: string; code: string };
const copy: Record<SecretaryState, StateCopy> = {
  BOOTING:      { en: "INITIALIZING",  code: "SYS.00" },
  SLEEP:        { en: "STANDBY",       code: "SYS.01" },
  WAKING:       { en: "AWAKENING",     code: "SYS.02" },
  LISTENING:    { en: "LISTENING",     code: "COM.10" },
  TRANSCRIBING: { en: "TRANSCRIBING",  code: "COM.11" },
  THINKING:     { en: "REASONING",     code: "AI.20"  },
  APPROVAL:     { en: "AUTHORIZATION", code: "SEC.30" },
  SPEAKING:     { en: "RESPONDING",    code: "COM.12" },
  ERROR:        { en: "RECOVERY",      code: "ERR.90" },
  OFFLINE:      { en: "LINK OFFLINE",  code: "NET.91" },
};

// 手拍子の閾値は端末内に持つ。起動方式の確定値は毎回上書きし、
// 保存済みの古いsingle設定に負けないようにする（2026-09-02、タイピング誤起動対策）。
function loadClapSettings(): ClapSettings {
  try {
    const saved = JSON.parse(localStorage.getItem("clap-settings") || "{}");
    return { ...DEFAULT_CLAP_SETTINGS, ...saved, hfMin: 0.2, gapMin: 250, gapMax: 800, mode: "double" };
  } catch {
    return { ...DEFAULT_CLAP_SETTINGS };
  }
}

function saveClapSettings(settings: ClapSettings): void {
  try {
    localStorage.setItem("clap-settings", JSON.stringify(settings));
  } catch {
    // Safari のプライベートモードは保存を拒否する。検出自体はメモリ上の設定で続く
  }
}

export default function App() {
  const [state, setState] = useState<SecretaryState>("BOOTING");
  const [mic, setMic] = useState<"idle" | "on" | "denied">("idle");
  const [logs, setLogs] = useState<ClapLog[]>([]);
  const [debug, setDebug] = useState(false);
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
  // 文字回答カード（1段目）の中身。音声読み上げの代わり（2026-09-02）。
  // 質問ごとに1件。「続けて聞く」で同じ画面へ積み増す
  const [qa, setQa] = useState<QAExchange[]>([]);
  const qaIdRef = useRef(0);
  const [approval, setApproval] = useState<{ id: string; summary: string; files: string[]; diff: string; warnings: string[] } | null>(null);
  // マイクが止まったまま起こせない状態。ユーザー操作が要るので画面に出す
  const [micStalled, setMicStalled] = useState(false);
  // 画面を消させない（常設端末なので寝ると指パッチンも聞けない）
  const [awake, setAwake] = useState(false);
  const wakeLock = useMemo(() => new ScreenWakeLock(), []);

  const socketRef = useRef<ReconnectingSocket | null>(null);
  const wakeStartedRef = useRef(false);
  // 検出コールバックは再生成しない（依存配列が空）ので、最新の状態は ref 経由で見る
  const stateRef = useRef(state);
  stateRef.current = state;

  const send = (event: SecretaryEvent) => setState(current => transition(current, event));

  // 文字回答カードの操作。詳しくは components/AnswerCard.tsx
  const openQaSession = (question: string, phase: QAPhase) =>
    setQa([{ id: ++qaIdRef.current, question, lines: [], phase }]);
  const appendQaExchange = (question: string, phase: QAPhase) =>
    setQa(prev => [...prev, { id: ++qaIdRef.current, question, lines: [], phase }]);
  const updateLastQa = (patch: Partial<QAExchange>) =>
    setQa(prev => {
      if (!prev.length) return prev;
      const next = [...prev];
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });
  const appendQaLines = (lines: string[]) =>
    setQa(prev => {
      if (!prev.length || !lines.length) return prev;
      const next = [...prev];
      const last = next[next.length - 1];
      next[next.length - 1] = { ...last, lines: [...last.lines, ...lines] };
      return next;
    });
  const appendQaLine = (line: string) => appendQaLines([line]);

  const detector = useMemo(() => new ClapDetector(
    settings,
    // 起こすのは待機中だけ。会話中の物音で状態を飛ばさない
    () => {
      if (stateRef.current !== "SLEEP") return;
      // 拍手を会話開始の固定入力としてPCへ送る。マイクで「なに？」を
      // 聞き直す必要がなく、Codexへ即時に渡せる。
      const question = "なにしよう？";
      socketRef.current?.send({ type: "text.input", text: question });
      openQaSession(question, "thinking");
      send("CLAP_DETECTED");
    },
    next => {
      setLogs(next);
      const last = next.at(-1);
      if (last) socketRef.current?.send({ type: "clap.candidate", ...last });
    },
  ), []);
  // 録音した 16kHz PCM は binary フレームで送る（DESIGN.md §8/§12）。
  // ただし送るのは §4 のとおり「会話中」だけ。待機中は指パッチ判定だけを
  // 端末で回す（detector はこのコールバックとは別に常時回っている）。
  // 常時送っていたため、エージェントが考えている20〜40秒のあいだにも音声が
  // 溜まり続け、接続が切れて STANDBY へ戻っていた（2026-09-01 実機）
  const microphone = useMemo(
    () => new ClapMicrophone(detector, chunk => {
      if (stateRef.current !== "LISTENING") return;
      socketRef.current?.sendAudio(chunk);
    }),
    [detector]);

  useEffect(() => { detector.update(settings); saveClapSettings(settings); }, [detector, settings]);

  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new ReconnectingSocket(
      `${protocol}://${location.host}/ws`,
      (status: SocketStatus) => {
        if (status === "open") send("CONNECTED");
        else if (status === "closed") send("DISCONNECTED");
      },
      message => {
        if (!message || typeof message !== "object") return;
        const event = message as Record<string, unknown>;

        // 壁紙を替えると caelestia の scheme.json が作り直され、
        // mode と必要な Material token 一式が届く。CSS 変数は html に反映する。
        if (event.type === "scheme.changed" && event.scheme && typeof event.scheme === "object") {
          const scheme = event.scheme as Partial<Scheme>;
          const valid = (scheme.mode === "light" || scheme.mode === "dark")
            && Object.keys(schemeVariables).every(key => typeof scheme[key as keyof Scheme] === "string" && HEX.test(String(scheme[key as keyof Scheme])));
          if (valid) {
            document.documentElement.dataset.theme = scheme.mode;
            for (const [key, variable] of Object.entries(schemeVariables)) {
              document.documentElement.style.setProperty(variable, String(scheme[key as keyof Scheme]));
            }
            // Safari はツールバーと status bar をこの色で塗る。固定値のままだと
            // 配色と合わず、画面の下に黒い帯が残る（2026-08-31、実機で約1cm）
            document.querySelector('meta[name="theme-color"]')
              ?.setAttribute("content", String(scheme.background));
          }
        }

        // 壁紙が変わった。版つきのURLで取り直す（同じ版ならブラウザの控えが効く）。
        // 版が空＝変換に失敗しているので、壁紙なしへ戻す
        if (event.type === "wallpaper.changed") {
          const version = typeof event.version === "string" ? event.version : "";
          document.documentElement.style.setProperty(
            "--wallpaper", version ? `url("/wallpaper.webp?v=${version}")` : "none");
        }

        // 答えを作り始めた。時間がかかるので画面で分かるようにする（§12）
        if (event.type === "agent.started") {
          updateLastQa({ phase: "thinking" });
          // 分単位かかる用件は、待ち時間の見当と止め方を最初に見せる。
          // 黙って何分も待たせないための約束（2026-09-02）
          if (event.long) appendQaLine("取りかかります。数分かかります。「やめて」で止まります。");
          send("AGENT_STARTED");
        }

        // 経過。長い仕事のあいだ、生きていることを見せ続ける
        if (event.type === "agent.progress") {
          const elapsed = typeof event.elapsed === "number" ? event.elapsed : 0;
          appendQaLine(`作業中… ${Math.floor(elapsed / 60)}分${String(elapsed % 60).padStart(2, "0")}秒`);
        }

        // 「やめて」で止めた。カードへ表示してから待機へ戻れる状態にする
        if (event.type === "agent.cancelled") {
          appendQaLine("止めました。");
          updateLastQa({ phase: "done" });
          send("IDLE");
        }

        // 答えが出た。文字回答カードへ追加表示する（読み上げは廃止・2026-09-02）
        if (event.type === "agent.completed") {
          const summary = typeof event.summary === "string" && event.summary ? event.summary
            : typeof event.spoken_reply === "string" ? event.spoken_reply : "";
          const lines = summary.split("\n").map(line => line.trim()).filter(Boolean);
          appendQaLines(lines.length ? lines : ["（答えが空でした）"]);
          updateLastQa({ phase: "done" });
          send("AGENT_COMPLETED");
        }

        // Phase 4: display the exact proposed files and diff before the real
        // Vault can be touched.  Approval itself is a separate HTTP request.
        if (event.type === "approval.required" && typeof event.job_id === "string") {
          setApproval({
            id: event.job_id,
            summary: typeof event.summary === "string" ? event.summary : "",
            files: Array.isArray(event.changed_files) ? event.changed_files.filter((file): file is string => typeof file === "string") : [],
            diff: typeof event.diff === "string" ? event.diff : "",
            // §11-3 対象が既に dirty なら承認前に見せる。押す前に読めないと意味がない
            warnings: Array.isArray(event.warnings) ? event.warnings.filter((line): line is string => typeof line === "string") : [],
          });
          setCaption("CHANGE REVIEW REQUIRED");
          appendQaLine("確認をお願いします（下の画面で承認／却下）。");
          send("APPROVAL_REQUIRED");
        }

        // 待機へ戻す指示（「ありがとう」など §9 の SYSTEM）
        if (event.type === "session.sleep") send("IDLE");

        // 話し始めた。待機へ戻るタイマーを止める（§8 の VAD による検出）
        if (event.type === "audio.speaking") setSpeaking(true);

        // 聞き取りが確定した（§12 audio.final）。「続けて聞く」で開いた
        // 空の質問行をここで埋める（拍手起動の固定質問はこの経路を通らない）
        if (event.type === "audio.final" && typeof event.text === "string") {
          setCaption(event.text);
          updateLastQa({ question: event.text, phase: "thinking" });
          send("AUDIO_FINAL");
        }

        // 書き起こしに失敗した。黙って戻らず理由を出す（§17）
        if (event.type === "system.error") {
          const message = typeof event.message === "string" ? event.message : "";
          if (event.code === "STT_FAILED") {
            // その場では寝ない。拍手の余韻で空振りすることがあり、
            // 即座に寝ると話しかける前に落ちる。文言を見せてから少し待って戻す
            setCaption(message || "聞き取れませんでした");
            appendQaLine(message || "聞き取れませんでした");
            updateLastQa({ phase: "done" });
            setHeardNothingAt(Date.now());
          } else {
            setCaption(message);
            appendQaLine(message);
            updateLastQa({ phase: "done" });
            send("SYSTEM_ERROR");
          }
        }

        // 3段目の実測（5秒間隔）。形が違うものは捨てて、前の値を残す
        if (event.type === "system.live" && event.apps && typeof event.apps === "object") {
          setLive(previous => ({
            apps: event.apps as LiveFacts["apps"],
            vault: (event.vault && typeof event.vault === "object" ? event.vault : previous.vault) as LiveFacts["vault"],
            phones: typeof event.phones === "number" ? event.phones : previous.phones,
          }));
        }

        // PC の実測値（5秒間隔）。届いた項目だけ差し替え、欠けていれば前の値を残す
        if (event.type === "system.telemetry") {
          const text = (key: string, fallback: string) => typeof event[key] === "string" ? event[key] as string : fallback;
          setTelemetry(previous => ({
            kernel: text("kernel", previous.kernel),
            uptime: text("uptime", previous.uptime),
            shell: text("shell", previous.shell),
            mem: text("mem", previous.mem),
            pkgs: typeof event.pkgs === "number" ? event.pkgs : previous.pkgs,
            user: text("user", previous.user),
            hname: text("hname", previous.hname),
            distro: text("distro", previous.distro),
            host: text("host", previous.host),
          }));
        }
      },
    );
    socketRef.current = socket;
    socket.start();
    return () => { socketRef.current = null; socket.stop(); };
  }, []);

  // ?state= / ?debug= / ?wake= の口。dev サーバー、または VITE_PREVIEW=1 で
  // 建てたビルドでだけ開く（実機確認は静的ビルドで行うのでビルドにも要る）。
  const previewable = import.meta.env.DEV || import.meta.env.VITE_PREVIEW === "1";
  const params = previewable ? new URLSearchParams(location.search) : null;

  // ?wake=15 で15秒ごとに指パッチン相当を撃つ（プレビュービルドのみ）。
  // 起動→リッスン→待機の一巡を、声も物音も無しに確かめるための口。
  const wakeEvery = Number(params?.get("wake") ?? 0);
  useEffect(() => {
    if (!wakeEvery) return;
    const id = setInterval(() => {
      if (stateRef.current === "SLEEP") send("CLAP_DETECTED");
    }, wakeEvery * 1000);
    return () => clearInterval(id);
  }, [wakeEvery]);

  // 聞き取れなかったときは、文言を5秒見せてから待機へ戻す
  useEffect(() => {
    if (!heardNothingAt) return;
    const id = setTimeout(() => { setHeardNothingAt(0); setQa([]); send("IDLE"); }, HEARD_NOTHING_MS);
    return () => clearTimeout(id);
  }, [heardNothingAt]);

  // 待機へ戻ったら文字回答カードを閉じる。どの経路（ボタン・タイムアウト・
  // エラー復帰）で戻っても、ここで確実に片付ける
  useEffect(() => { if (state === "SLEEP" && qa.length) setQa([]); }, [state, qa.length]);

  // 録音は LISTENING の間だけ。待機中に送り続けない
  useEffect(() => {
    if (mic !== "on") return;
    if (state !== "LISTENING") { microphone.setRecording(false); return; }
    // 拍手の余韻や「続けて聞く」タップの音が発話として書き起こされ、
    // 空振りして待機へ戻っていた（2026-08-31 のログ: utterance 360ms → ''）。
    // 音が消えてから録る
    const id = setTimeout(() => microphone.setRecording(true), SNAP_TAIL_MS);
    return () => { clearTimeout(id); microphone.setRecording(false); };
  }, [microphone, mic, state]);

  // 画面ロックの見張り。OS の都合で解放されるので、外れていたら取り直す
  useEffect(() => {
    if (mic !== "on" || !ScreenWakeLock.supported) return;
    const id = setInterval(() => { void wakeLock.enable().then(setAwake); }, 10000);
    return () => clearInterval(id);
  }, [wakeLock, mic]);

  // マイクの見張り。iOS はセッション中断でマイクが止まったまま戻らないことが
  // あるので（2026-08-31 実機）、2秒ごとに生死を見て起こし直す。
  // 起こせなかったときは画面に出す（黙って効かないままにしない）
  useEffect(() => {
    if (mic !== "on") return;
    let stalls = 0;
    const id = setInterval(async () => {
      if (microphone.health().ok) { stalls = 0; setMicStalled(false); return; }

      // 読み上げ直後は戻るまでに間がある。続けて詰まったときだけ手当てする
      stalls += 1;
      if (stalls < 2) return;
      const revived = await microphone.ensureRunning();
      setMicStalled(!revived);
      socketRef.current?.send({ type: "mic.health", ...microphone.health(), revived });
      if (revived) stalls = 0;
    }, 2000);
    return () => clearInterval(id);
  }, [microphone, mic]);

  useEffect(() => {
    // 再描画のたびに再実行されても、起動ごとに一度だけ実行する
    if (state === "WAKING" && !wakeStartedRef.current) {
      wakeStartedRef.current = true;
      setCaption("");
      setSpeaking(false);
      setHeardNothingAt(0);
      const id = setTimeout(() => send("WAKE_FINISHED"), WAKE_ANIM_MS);
      return () => clearTimeout(id);
    }
    if (state !== "WAKING") wakeStartedRef.current = false;
    if (state === "LISTENING") {
      // 話し始めていたら待機へ戻さない。言い終わるまで待つ
      // （終端は VAD が決める。長すぎる発話は §6 の 30秒で必ず切れる）
      if (speaking) return;
      const id = setTimeout(() => send("IDLE"), LISTEN_IDLE_MS);
      return () => clearTimeout(id);
    }
    // 文字回答カードを見せたまま自動で待機へ戻す（読み上げ廃止・2026-09-02）。
    // 「戻る」「続けて聞く」のどちらかを押せばこのタイマーは次の描画で消える
    if (state === "SPEAKING") {
      const id = setTimeout(() => { setQa([]); send("IDLE"); }, POST_ANSWER_IDLE_MS);
      return () => clearTimeout(id);
    }
    if (state === "ERROR") {
      const id = setTimeout(() => send("RETRY"), 5000);
      return () => clearTimeout(id);
    }
  }, [state, speaking]);

  async function enableMic() {
    // タップ自体が届いているかを切り分けるための即時マーカー
    // （2026-09-02、「押しても何も出ない」の原因調査）
    setCaption("ENABLE MIC を押しました…");
    try {
      await microphone.start();
      setMic("on");
      // 画面ロックの解除はユーザー操作の文脈でしか取れないことがある。
      // マイク許可と同じ操作のうちに取っておく
      setAwake(await wakeLock.enable());
    } catch (error) {
      // 何が失敗したか画面に出す。「押しても何も起きない」の原因切り分けに要る
      // （2026-09-02、catch で握りつぶしていて原因が見えなかった）
      const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      setMic("denied");
      setCaption(`マイクを開始できません: ${detail}`);
      send("SYSTEM_ERROR");
    }
  }

  // 「戻る」：カードを閉じて待機へ。「続けて聞く」：カードは残したまま
  // 次の発話を録る（WAKING を経由しない）
  function closeQa() { setQa([]); send("IDLE"); }
  function continueQa() { appendQaExchange("", "listening"); send("CONTINUE"); }

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
      appendQaLines(summary.split("\n").map(line => line.trim()).filter(Boolean));
      updateLastQa({ phase: "done" });
      send("AGENT_COMPLETED");
    } catch (error) {
      const message = error instanceof Error ? error.message : "APPROVAL FAILED";
      setCaption(message);
      appendQaLine(message);
      updateLastQa({ phase: "done" });
      send("SYSTEM_ERROR");
    }
  }

  const preview = params?.get("state")?.toUpperCase() as SecretaryState | undefined;
  const view = preview && preview in copy ? preview : state;
  const content = copy[view];
  const connected = !["BOOTING", "OFFLINE", "ERROR"].includes(view);
  const showDebug = debug || params?.get("debug") === "1";

  // sysmon の右列と同じ3段。上から fetch / dots / 状態（tty-clock の位置）。
  // 質問が始まったら1段目を文字回答カードへ差し替える（読み上げ廃止・2026-09-02）
  return <main className={`shell state-${view.toLowerCase()}`}>
    <Ambience state={view} />
    {qa.length
      ? <AnswerCard exchanges={qa} onBack={closeQa} onContinue={continueQa} />
      : <Fetch facts={telemetry} link={connected ? "LINKED" : "OFFLINE"} />}

    <section className="core-stage panel">
      <LavaCore state={view} />
    </section>

    <Live state={content.en} code={content.code} live={live} caption={caption} />

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
    {showDebug ? <DebugPanel logs={logs} settings={settings} onSettings={setSettings} onClose={() => setDebug(false)} /> : null}
    {/* ホーム画面 PWA では start_url が "/" なので ?size=1 が届かない。
        崩れるのが standalone のときだけなので、DEBUG からも出す */}
    {showDebug || params?.get("size") === "1" ? <SizeProbe /> : null}
  </main>;
}
