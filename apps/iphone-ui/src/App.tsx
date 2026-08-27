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

  return <main className={`${state === "SLEEP" ? "sleep " : ""}state-${state.toLowerCase()}`}>
    <div className="hud" aria-hidden="true">
      <div className="orbital orbital-a" /><div className="orbital orbital-b" /><div className="orbital orbital-c" />
      <div className="reticle"><i /><i /><i /><i /></div>
      <div className="pulse-core" /><div className="scan-beam" />
    </div>
    <section className="panel"><header><span className={`dot ${state === "OFFLINE" ? "off" : ""}`} />AI SECRETARY / LIVE RESPONSE</header>
      <div className="eyebrow">COGNITIVE INTERFACE · 01</div>
      <h1>{state === "SLEEP" ? "STANDBY" : labels[state]}</h1>
      <div className="state-rule"><span>{labels[state]}</span><b /></div>
      <p>{mic === "on" ? "指を鳴らすのを待っています" : mic === "denied" ? "マイクを許可してください" : "最初にマイクを有効にしてください"}</p>
      {mic !== "on" && <button onClick={enableMic}>マイクを有効にする</button>}
      <button className="secondary" onClick={() => setDebug(x => !x)}>検出ログ {debug ? "を閉じる" : "を開く"}</button>
      {debug && <DebugPanel logs={logs} settings={settings} onSettings={setSettings} />}
      <footer>JARVIS SYSTEM <span>LOCAL / SECURE</span></footer>
    </section><Secretary state={state} />
  </main>;
}
