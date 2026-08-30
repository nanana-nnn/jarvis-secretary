import { useEffect, useMemo, useRef, useState } from "react";
import { ReconnectingSocket, type SocketStatus } from "./api/socket";
import { ClapDetector } from "./audio/clap-detector";
import { ClapMicrophone } from "./audio/microphone";
import { DEFAULT_CLAP_SETTINGS, type AudioMetrics, type ClapLog, type ClapSettings } from "./audio/types";
import { DebugPanel } from "./components/DebugPanel";
import { PixelCore } from "./components/PixelCore";
import { transition } from "./states/machine";
import type { SecretaryEvent, SecretaryState } from "./states/types";

// WAKE_ANIM_MS は §15 の指パッチン衝撃波と状態遷移を揃える。
// LISTEN_IDLE_MS を過ぎると自分から待機へ戻る（言い忘れたまま起きっぱなしにしない）。
const WAKE_ANIM_MS = 250;
const LISTEN_IDLE_MS = 8000;

// サーバーから来る差し色を検査する。信頼せずに形だけ見る。
const HEX = /^#[0-9a-f]{6}$/i;

type Telemetry = { load: number; memory: number; uptime: string; host: string };
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
 * 状態ごとの表示文。
 * jp は日本語1行、en と code は英字。DESIGN.md の作法どおり同じ行に混ぜない。
 * code は状態の系統が一目で分かるよう接頭辞を揃えてある（SYS / COM / AI / SEC / ERR / NET）。
 */
type StateCopy = { jp: string; en: string; message: string; code: string };
const copy: Record<SecretaryState, StateCopy> = {
  BOOTING:      { jp: "起動シーケンス",   en: "INITIALIZING",  message: "秘書コアとLinuxホストを接続しています",   code: "SYS.00" },
  SLEEP:        { jp: "待機しています",   en: "STANDBY",       message: "指の音を合図に、いつでも起動できます",     code: "SYS.01" },
  WAKING:       { jp: "お呼びですか",     en: "AWAKENING",     message: "音声インターフェースを展開しています",     code: "SYS.02" },
  LISTENING:    { jp: "話してください",   en: "LISTENING",     message: "あなたの声を聞いています",                 code: "COM.10" },
  TRANSCRIBING: { jp: "言葉にしています", en: "TRANSCRIBING",  message: "音声をローカルで解析しています",           code: "COM.11" },
  THINKING:     { jp: "考えています",     en: "REASONING",     message: "Vaultと現在の状況を照合しています",       code: "AI.20"  },
  APPROVAL:     { jp: "確認してください", en: "AUTHORIZATION", message: "書き込みは承認されるまで実行しません",     code: "SEC.30" },
  SPEAKING:     { jp: "回答します",       en: "RESPONDING",    message: "処理が完了しました",                       code: "COM.12" },
  ERROR:        { jp: "問題を検知",       en: "RECOVERY",      message: "安全に停止し、復帰を試みています",         code: "ERR.90" },
  OFFLINE:      { jp: "接続を待っています", en: "LINK OFFLINE", message: "Linuxホストへの再接続を続けています",     code: "NET.91" },
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
  // 実測値が届くまでの初期値。数字を作らないので load/memory は 0、uptime は「—」
  const [telemetry, setTelemetry] = useState<Telemetry>({ load: 0, memory: 0, uptime: "—", host: "JARVIS" });
  const [settings, setSettings] = useState<ClapSettings>(loadClapSettings);

  const socketRef = useRef<ReconnectingSocket | null>(null);
  const metricsRef = useRef<AudioMetrics>({ at: 0, rms: 0, hfRatio: 0, riseMs: 0 });
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
  const microphone = useMemo(() => new ClapMicrophone(detector, metrics => { metricsRef.current = metrics; }), [detector]);

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
        const event = message as { type?: unknown; scheme?: unknown; load?: unknown; memory?: unknown; uptime?: unknown; host?: unknown };

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
          }
        }

        // PC の実測値（5秒間隔）。数値が揃っていないメッセージは捨てる
        if (event.type === "system.telemetry" && typeof event.load === "number" && typeof event.memory === "number") {
          setTelemetry({
            load: event.load,
            memory: event.memory,
            uptime: String(event.uptime ?? "—"),
            host: String(event.host ?? "JARVIS"),
          });
        }
      },
    );
    socketRef.current = socket;
    socket.start();
    return () => { socketRef.current = null; socket.stop(); };
  }, []);

  useEffect(() => {
    if (state === "WAKING") {
      speechSynthesis.speak(new SpeechSynthesisUtterance("はい、どうしました？"));
      const id = setTimeout(() => send("WAKE_FINISHED"), WAKE_ANIM_MS);
      return () => clearTimeout(id);
    }
    if (state === "LISTENING") {
      const id = setTimeout(() => send("IDLE"), LISTEN_IDLE_MS);
      return () => clearTimeout(id);
    }
    if (state === "ERROR") {
      const id = setTimeout(() => send("RETRY"), 5000);
      return () => clearTimeout(id);
    }
  }, [state]);

  async function enableMic() {
    try {
      await microphone.start();
      setMic("on");
    } catch {
      setMic("denied");
      send("SYSTEM_ERROR");
    }
  }

  // ?state=LISTENING で任意の状態を描画する（配線は変えず見た目だけ差し替える）。
  // dev サーバー、または VITE_PREVIEW=1 で建てたビルドでだけ開く。
  // 実機確認は静的ビルドで行うのでビルドにも口が要る（README「実機確認」）。
  const previewable = import.meta.env.DEV || import.meta.env.VITE_PREVIEW === "1";
  const params = previewable ? new URLSearchParams(location.search) : null;
  const preview = params?.get("state")?.toUpperCase() as SecretaryState | undefined;
  const view = preview && preview in copy ? preview : state;
  const content = copy[view];
  const connected = !["BOOTING", "OFFLINE", "ERROR"].includes(view);
  const showDebug = debug || params?.get("debug") === "1";

  return <main className={`shell state-${view.toLowerCase()}`}>
    <header className="topbar">
      <div className="brand"><b>JARVIS</b><span>LOCAL INTELLIGENCE</span></div>
      <div className={`pc-link ${connected ? "online" : ""}`}>
        <span className="signal" />
        <div><strong>{connected ? "LINKED" : "OFFLINE"}</strong><small>{telemetry.host.toUpperCase()}</small></div>
      </div>
    </header>

    <section className="core-stage">
      <div className="grid-field" aria-hidden="true" />
      <PixelCore state={view} metricsRef={metricsRef} />
      <span className="core-mark" aria-hidden="true">J</span>
    </section>

    <section className="state-panel">
      <small>{content.code} / {content.en}</small>
      <h1>{content.jp}</h1>
      <p>{content.message}</p>
    </section>

    <section className="terminal-id" aria-label="JARVIS システム情報">
      <pre>{`     __  ___    ____ _    _______ _____
 __ / / /   |  / __ \\ |  / /  _/ ___/
/ // / / /| | / /_/ / | / // / \\__ \\
\\___/ /_/  |_/_/ |_| |___/___/____/`}</pre>
      <dl>
        <div><dt>CORE</dt><dd>JARVIS</dd></div>
        <div><dt>HOST</dt><dd>{telemetry.host}</dd></div>
        <div><dt>SYSTEM</dt><dd>CachyOS / Hyprland</dd></div>
        <div><dt>MEMORY</dt><dd>Start Vault</dd></div>
        <div><dt>INPUT</dt><dd>SNAP + VOICE</dd></div>
      </dl>
    </section>

    <footer className="controls">
      <div className="system-flags"><span>VAULT 5</span><span>LAN SECURE</span><span>NO CLOUD</span></div>
      <div className="actions">
          {mic !== "on"
            ? <button className="primary-action" onClick={enableMic}>マイクを有効にする</button>
            : <span className="mic-live">● MIC LIVE</span>}
          {mic === "denied" ? <span className="warning">MIC DENIED</span> : null}
          <button className="debug-action" onClick={() => setDebug(value => !value)} aria-label="検出ログ">•••</button>
      </div>
    </footer>
    {showDebug ? <DebugPanel logs={logs} settings={settings} onSettings={setSettings} /> : null}
  </main>;
}
