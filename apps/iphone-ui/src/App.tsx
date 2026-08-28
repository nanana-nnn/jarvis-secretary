import { useEffect, useMemo, useRef, useState } from "react";
import { ReconnectingSocket, type SocketStatus } from "./api/socket";
import { ClapDetector } from "./audio/clap-detector";
import { ClapMicrophone } from "./audio/microphone";
import { DEFAULT_CLAP_SETTINGS, type ClapLog, type ClapSettings } from "./audio/types";
import { DebugPanel } from "./components/DebugPanel";
import { Secretary } from "./components/Secretary";
import { transition } from "./states/machine";
import type { SecretaryEvent, SecretaryState } from "./states/types";

const WAKE_ANIM_MS = 250, LISTEN_IDLE_MS = 8000;
const labels: Record<SecretaryState, string> = { BOOTING:"CONNECTING",SLEEP:"STANDBY",WAKING:"AWAKENING",LISTENING:"LISTENING",TRANSCRIBING:"TRANSCRIBING",THINKING:"THINKING",APPROVAL:"APPROVAL REQUIRED",SPEAKING:"RESPONDING",ERROR:"SYSTEM ERROR",OFFLINE:"OFFLINE" };
// 状態の説明は日本語1行だけ。latin と同じ行に混ぜない（design.md）
const notes: Record<SecretaryState, string> = {
  BOOTING:"PCに接続しています", SLEEP:"目を閉じて、指の音だけを聴いています", WAKING:"起きます",
  LISTENING:"はい、どうしました？", TRANSCRIBING:"聞き取っています", THINKING:"考えています",
  APPROVAL:"書き込む前に確認してください", SPEAKING:"答えています",
  ERROR:"復帰を試みています", OFFLINE:"PCと未接続です。再接続を続けています",
};

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
    // Safari can deny storage access; clap detection can still use in-memory settings.
  }
}

export default function App() {
  const [state, setState] = useState<SecretaryState>("BOOTING");
  const [mic, setMic] = useState<"idle"|"on"|"denied">("idle");
  const [logs, setLogs] = useState<ClapLog[]>([]);
  const [debug, setDebug] = useState(false);
  const [settings, setSettings] = useState<ClapSettings>(loadClapSettings);
  const socketRef = useRef<ReconnectingSocket | null>(null);
  const stateRef = useRef(state); stateRef.current = state;
  const send = (event: SecretaryEvent) => setState(current => transition(current, event));
  const detector = useMemo(() => new ClapDetector(settings, () => { if (stateRef.current === "SLEEP") send("CLAP_DETECTED"); }, nextLogs => {
    setLogs(nextLogs);
    const latest = nextLogs.at(-1);
    if (latest) socketRef.current?.send({ type: "clap.candidate", ...latest });
  }), []);
  const microphone = useMemo(() => new ClapMicrophone(detector), [detector]);

  useEffect(() => { detector.update(settings); saveClapSettings(settings); }, [detector, settings]);
  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new ReconnectingSocket(`${protocol}://${location.host}/ws`, (status: SocketStatus) => {
      if (status === "open") send("CONNECTED"); else if (status === "closed") send("DISCONNECTED");
    });
    socketRef.current = socket;
    socket.start(); return () => { socketRef.current = null; socket.stop(); };
  }, []);
  useEffect(() => {
    if (state === "WAKING") { speechSynthesis.speak(new SpeechSynthesisUtterance("はい、どうしました？")); const id = window.setTimeout(() => send("WAKE_FINISHED"), WAKE_ANIM_MS); return () => clearTimeout(id); }
    if (state === "LISTENING") { const id = window.setTimeout(() => send("IDLE"), LISTEN_IDLE_MS); return () => clearTimeout(id); }
    if (state === "ERROR") { const id = window.setTimeout(() => send("RETRY"), 5000); return () => clearTimeout(id); }
  }, [state]);
  async function enableMic() { try { await microphone.start(); setMic("on"); } catch { setMic("denied"); send("SYSTEM_ERROR"); } }

  // 開発時のみ ?state=LISTENING で任意の状態を描画する（配線は変えず見た目だけ差し替える）
  const params = import.meta.env.DEV ? new URLSearchParams(location.search) : null;
  const preview = params?.get("state")?.toUpperCase() as SecretaryState | undefined;
  const view = preview && preview in labels ? preview : state;
  const showDebug = debug || params?.get("debug") === "1";
  const live = view !== "OFFLINE" && view !== "ERROR" && view !== "BOOTING";
  const last = logs.at(-1);

  return <main className={`state-${view.toLowerCase()}`}>
    <Secretary state={view} />

    <section className="console">
      <header className="rail">
        <span className={`beacon ${live ? "" : "cold"}`} aria-hidden="true" />
        <span className="rail-name">JARVIS SECRETARY</span>
        <span className="rail-tail">LAN ONLY</span>
      </header>

      <div className="readout">
        <h1>{labels[view]}</h1>
        <div className="tick" aria-hidden="true" />
        <p>{notes[view]}</p>
      </div>

      <dl className="gauges">
        <div><dt>RATIO</dt><dd>{settings.ratio.toFixed(1)}</dd></div>
        <div><dt>HF</dt><dd>{settings.hfMin.toFixed(2)}</dd></div>
        <div><dt>MODE</dt><dd>{settings.mode.toUpperCase()}</dd></div>
        <div><dt>LAST RMS</dt><dd>{last ? last.rms.toFixed(3) : "—"}</dd></div>
      </dl>

      <div className="actions">
        {mic !== "on" && <button className="key" onClick={enableMic}>マイクを有効にする</button>}
        {mic === "denied" && <span className="warn">マイクが拒否されています</span>}
        <button className="ghost" onClick={() => setDebug(x => !x)}>{debug ? "ログを閉じる" : "検出ログ"}</button>
      </div>
    </section>

    {showDebug && <DebugPanel logs={logs} settings={settings} onSettings={setSettings} />}
  </main>;
}
