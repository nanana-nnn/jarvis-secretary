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
const labels: Record<SecretaryState, string> = { BOOTING:"接続中",SLEEP:"待機中",WAKING:"起動中",LISTENING:"聞いています",TRANSCRIBING:"文字起こし中",THINKING:"考えています",APPROVAL:"確認してください",SPEAKING:"回答中",ERROR:"エラー",OFFLINE:"PCと未接続" };

export default function App() {
  const [state, setState] = useState<SecretaryState>("BOOTING");
  const [mic, setMic] = useState<"idle"|"on"|"denied">("idle");
  const [logs, setLogs] = useState<ClapLog[]>([]);
  const [debug, setDebug] = useState(false);
  const [settings, setSettings] = useState<ClapSettings>(() => ({ ...DEFAULT_CLAP_SETTINGS, ...JSON.parse(localStorage.getItem("clap-settings") || "{}") }));
  const stateRef = useRef(state); stateRef.current = state;
  const send = (event: SecretaryEvent) => setState(current => transition(current, event));
  const detector = useMemo(() => new ClapDetector(settings, () => { if (stateRef.current === "SLEEP") send("CLAP_DETECTED"); }, setLogs), []);
  const microphone = useMemo(() => new ClapMicrophone(detector), [detector]);

  useEffect(() => { detector.update(settings); localStorage.setItem("clap-settings", JSON.stringify(settings)); }, [detector, settings]);
  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const host = import.meta.env.VITE_SERVER_HOST || location.hostname;
    const port = import.meta.env.VITE_SERVER_PORT || "8787";
    const socket = new ReconnectingSocket(`${protocol}://${host}:${port}/ws`, (status: SocketStatus) => {
      if (status === "open") send("CONNECTED"); else if (status === "closed") send("DISCONNECTED");
    });
    socket.start(); return () => socket.stop();
  }, []);
  useEffect(() => {
    if (state === "WAKING") { speechSynthesis.speak(new SpeechSynthesisUtterance("はい、どうしました？")); const id = window.setTimeout(() => send("WAKE_FINISHED"), WAKE_ANIM_MS); return () => clearTimeout(id); }
    if (state === "LISTENING") { const id = window.setTimeout(() => send("IDLE"), LISTEN_IDLE_MS); return () => clearTimeout(id); }
    if (state === "ERROR") { const id = window.setTimeout(() => send("RETRY"), 5000); return () => clearTimeout(id); }
  }, [state]);
  async function enableMic() { try { await microphone.start(); setMic("on"); } catch { setMic("denied"); send("SYSTEM_ERROR"); } }

  return <main className={state === "SLEEP" ? "sleep" : ""}>
    <section className="panel"><header><span className={`dot ${state === "OFFLINE" ? "off" : ""}`} />{labels[state]}</header>
      <h1>{state === "SLEEP" ? "JARVIS" : labels[state]}</h1>
      <p>{mic === "on" ? "ダブルクラップを待っています" : mic === "denied" ? "マイクを許可してください" : "最初にマイクを有効にしてください"}</p>
      {mic !== "on" && <button onClick={enableMic}>マイクを有効にする</button>}
      <button className="secondary" onClick={() => setDebug(x => !x)}>検出ログ {debug ? "を閉じる" : "を開く"}</button>
      {debug && <DebugPanel logs={logs} settings={settings} onSettings={setSettings} />}
    </section><Secretary state={state} />
  </main>;
}
