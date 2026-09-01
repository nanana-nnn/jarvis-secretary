import { useEffect, useMemo, useRef, useState } from "react";
import { ReconnectingSocket, type SocketStatus } from "./api/socket";
import { ClapDetector } from "./audio/clap-detector";
import { ClapMicrophone } from "./audio/microphone";
import { ScreenWakeLock } from "./audio/wake-lock";
import { DEFAULT_CLAP_SETTINGS, type ClapLog, type ClapSettings } from "./audio/types";
import { DebugPanel } from "./components/DebugPanel";
import { Ambience } from "./components/Ambience";
import { Fetch, type Facts } from "./components/Fetch";
import { LavaCore } from "./components/LavaCore";
import { Live, type LiveFacts } from "./components/Live";
import { SizeProbe } from "./components/SizeProbe";
import { transition } from "./states/machine";
import type { SecretaryEvent, SecretaryState } from "./states/types";

// WAKE_ANIM_MS は §15 の指パッチン衝撃波と状態遷移を揃える。
// LISTEN_IDLE_MS を過ぎると自分から待機へ戻る（言い忘れたまま起きっぱなしにしない）。
const WAKE_ANIM_MS = 250;
// §6 の表は 8000。実機だと指を鳴らして言いかけるだけで寝てしまい短すぎたので
// 延ばしてある。あわせて、話し始めたらこのタイマーは止める（下の speaking）
const LISTEN_IDLE_MS = 20000;
const POST_SPEAK_IDLE_MS = 8000;   // §6 読み上げ後に待機へ戻る
const SNAP_TAIL_MS = 450;          // 指パッチンの余韻が消えるまで録音を待つ
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

// 手拍子の閾値は端末内に持つ。hfMin と mode は毎回上書きする
// （2026-08-26 に指パッチン1回へ変更した値で、保存済みの古い設定に負けないようにするため）。
function loadClapSettings(): ClapSettings {
  try {
    const saved = JSON.parse(localStorage.getItem("clap-settings") || "{}");
    return { ...DEFAULT_CLAP_SETTINGS, ...saved, hfMin: 0.2, mode: "single" };
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
  // 聞き取り結果の字幕。空文字は「まだ何も無い」を表す
  const [caption, setCaption] = useState("");
  // サーバーが発話を検出した。話している間に待機へ戻さないための印
  const [speaking, setSpeaking] = useState(false);
  // 「聞き取れませんでした」を出した時刻。少し見せてから待機へ戻す
  const [heardNothingAt, setHeardNothingAt] = useState(0);
  // 読み上げる答え。聞き取った文ではなく、これを喋る
  const [reply, setReply] = useState("");
  // マイクが止まったまま起こせない状態。ユーザー操作が要るので画面に出す
  const [micStalled, setMicStalled] = useState(false);
  // 画面を消させない（常設端末なので寝ると指パッチンも聞けない）
  const [awake, setAwake] = useState(false);
  const wakeLock = useMemo(() => new ScreenWakeLock(), []);

  const socketRef = useRef<ReconnectingSocket | null>(null);
  // 検出コールバックは再生成しない（依存配列が空）ので、最新の状態は ref 経由で見る
  const stateRef = useRef(state);
  stateRef.current = state;

  const send = (event: SecretaryEvent) => setState(current => transition(current, event));

  const detector = useMemo(() => new ClapDetector(
    settings,
    // 起こすのは待機中だけ。会話中の物音で状態を飛ばさない
    () => { if (stateRef.current === "SLEEP") send("CLAP_DETECTED"); },
    next => {
      setLogs(next);
      const last = next.at(-1);
      if (last) socketRef.current?.send({ type: "clap.candidate", ...last });
    },
  ), []);
  // 録音した 16kHz PCM は binary フレームで送る（DESIGN.md §8/§12）
  const microphone = useMemo(
    () => new ClapMicrophone(detector, chunk => socketRef.current?.sendAudio(chunk)),
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
          setCaption(`調べています…（${String(event.intent ?? "")}）`);
          send("AGENT_STARTED");
        }

        // 答えが出た。これを読み上げる（§10 spoken_reply）
        if (event.type === "agent.completed") {
          const spoken = typeof event.spoken_reply === "string" ? event.spoken_reply : "";
          setCaption(typeof event.summary === "string" && event.summary ? event.summary : spoken);
          setReply(spoken);
          send("AGENT_COMPLETED");
        }

        // 待機へ戻す指示（「ありがとう」など §9 の SYSTEM）
        if (event.type === "session.sleep") send("IDLE");

        // 話し始めた。待機へ戻るタイマーを止める（§8 の VAD による検出）
        if (event.type === "audio.speaking") setSpeaking(true);

        // 聞き取りが確定した（§12 audio.final）。字幕に出して読み上げへ進む
        if (event.type === "audio.final" && typeof event.text === "string") {
          setCaption(event.text);
          send("AUDIO_FINAL");
        }

        // 書き起こしに失敗した。黙って戻らず理由を出す（§17）
        if (event.type === "system.error") {
          const message = typeof event.message === "string" ? event.message : "";
          if (event.code === "STT_FAILED") {
            // その場では寝ない。指パッチンの余韻で空振りすることがあり、
            // 即座に寝ると話しかける前に落ちる。文言を見せてから少し待って戻す
            setCaption(message || "聞き取れませんでした");
            setHeardNothingAt(Date.now());
          } else {
            setCaption(message);
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
    const id = setTimeout(() => { setHeardNothingAt(0); send("IDLE"); }, HEARD_NOTHING_MS);
    return () => clearTimeout(id);
  }, [heardNothingAt]);

  // 録音は LISTENING の間だけ。待機中に送り続けない
  useEffect(() => {
    if (mic !== "on") return;
    if (state !== "LISTENING") { microphone.setRecording(false); return; }
    // 指パッチンの余韻が発話として書き起こされ、空振りして待機へ戻っていた
    // （2026-08-31 のログ: utterance 360ms → ''）。鳴らした音が消えてから録る
    const id = setTimeout(() => microphone.setRecording(true), SNAP_TAIL_MS);
    return () => { clearTimeout(id); microphone.setRecording(false); };
  }, [microphone, mic, state]);

  // 画面ロックの見張り。OS の都合で解放されるので、外れていたら取り直す
  useEffect(() => {
    if (mic !== "on" || !ScreenWakeLock.supported) return;
    const id = setInterval(() => { void wakeLock.enable().then(setAwake); }, 10000);
    return () => clearInterval(id);
  }, [wakeLock, mic]);

  // マイクの見張り。iOS は読み上げで録音セッションを止めることがあり、
  // 一度スリープすると指パッチンを拾わなくなっていた（2026-08-31 実機）。
  // onend だけに頼らず、2秒ごとに生死を見て起こし直す。
  // 起こせなかったときは画面に出す（黙って効かないままにしない）
  useEffect(() => {
    if (mic !== "on") return;
    let stalls = 0;
    const id = setInterval(async () => {
      // 読み上げ中にミュートされるのは iOS の正常な動き。ここで開き直すと
      // 毎回マイクを壊しに行くことになる（2026-08-31、2秒ごとに競合していた）
      if (speechSynthesis.speaking) { stalls = 0; return; }

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
    if (state === "WAKING") {
      setCaption("");
      setReply("");
      setSpeaking(false);
      setHeardNothingAt(0);
      const hello = new SpeechSynthesisUtterance("はい、どうしました？");
      hello.lang = "ja-JP";
      // 読み上げが終わった直後に必ず起こし直す。iOS は再生で録音を止めることがある
      hello.onend = () => { void microphone.ensureRunning(); };
      speechSynthesis.speak(hello);
      const id = setTimeout(() => send("WAKE_FINISHED"), WAKE_ANIM_MS);
      return () => clearTimeout(id);
    }
    if (state === "LISTENING") {
      // 話し始めていたら待機へ戻さない。言い終わるまで待つ
      // （終端は VAD が決める。長すぎる発話は §6 の 30秒で必ず切れる）
      if (speaking) return;
      const id = setTimeout(() => send("IDLE"), LISTEN_IDLE_MS);
      return () => clearTimeout(id);
    }
    // 答えが返ったら読み上げて待機へ戻る（§10 spoken_reply を喋る）
    if (state === "SPEAKING") {
      const utterance = new SpeechSynthesisUtterance(reply);
      utterance.lang = "ja-JP";
      utterance.onend = () => { void microphone.ensureRunning(); };
      speechSynthesis.speak(utterance);
      const id = setTimeout(() => send("IDLE"), POST_SPEAK_IDLE_MS);
      return () => { clearTimeout(id); speechSynthesis.cancel(); };
    }
    if (state === "ERROR") {
      const id = setTimeout(() => send("RETRY"), 5000);
      return () => clearTimeout(id);
    }
  }, [state, reply, speaking]);

  async function enableMic() {
    try {
      await microphone.start();
      setMic("on");
      // 画面ロックの解除はユーザー操作の文脈でしか取れないことがある。
      // マイク許可と同じ操作のうちに取っておく
      setAwake(await wakeLock.enable());
    } catch {
      setMic("denied");
      send("SYSTEM_ERROR");
    }
  }

  const preview = params?.get("state")?.toUpperCase() as SecretaryState | undefined;
  const view = preview && preview in copy ? preview : state;
  const content = copy[view];
  const connected = !["BOOTING", "OFFLINE", "ERROR"].includes(view);
  const showDebug = debug || params?.get("debug") === "1";

  // sysmon の右列と同じ3段。上から fetch / dots / 状態（tty-clock の位置）
  return <main className={`shell state-${view.toLowerCase()}`}>
    <Ambience state={view} />
    <Fetch facts={telemetry} link={connected ? "LINKED" : "OFFLINE"} />

    <section className="core-stage panel">
      <LavaCore state={view} />
    </section>

    <Live state={content.en} code={content.code} live={live} caption={caption} />

    <footer className="controls">
      <div className="system-flags">
        <span>VAULT 5</span><span>LAN SECURE</span><span>NO CLOUD</span>
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
    {showDebug ? <DebugPanel logs={logs} settings={settings} onSettings={setSettings} /> : null}
    {/* ホーム画面 PWA では start_url が "/" なので ?size=1 が届かない。
        崩れるのが standalone のときだけなので、DEBUG からも出す */}
    {showDebug || params?.get("size") === "1" ? <SizeProbe /> : null}
  </main>;
}
