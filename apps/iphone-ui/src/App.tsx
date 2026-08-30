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
const HEX = /^#[0-9a-f]{6}$/i;
type Telemetry = { load: number; memory: number; uptime: string; host: string };
type StateCopy = { jp: string; en: string; message: string; code: string };
const copy: Record<SecretaryState, StateCopy> = {
  BOOTING:{jp:"起動シーケンス",en:"INITIALIZING",message:"秘書コアとLinuxホストを接続しています",code:"SYS.00"},
  SLEEP:{jp:"待機しています",en:"STANDBY",message:"指の音を合図に、いつでも起動できます",code:"SYS.01"},
  WAKING:{jp:"お呼びですか",en:"AWAKENING",message:"音声インターフェースを展開しています",code:"SYS.02"},
  LISTENING:{jp:"話してください",en:"LISTENING",message:"あなたの声を聞いています",code:"COM.10"},
  TRANSCRIBING:{jp:"言葉にしています",en:"TRANSCRIBING",message:"音声をローカルで解析しています",code:"COM.11"},
  THINKING:{jp:"考えています",en:"REASONING",message:"Vaultと現在の状況を照合しています",code:"AI.20"},
  APPROVAL:{jp:"確認してください",en:"AUTHORIZATION",message:"書き込みは承認されるまで実行しません",code:"SEC.30"},
  SPEAKING:{jp:"回答します",en:"RESPONDING",message:"処理が完了しました",code:"COM.12"},
  ERROR:{jp:"問題を検知",en:"RECOVERY",message:"安全に停止し、復帰を試みています",code:"ERR.90"},
  OFFLINE:{jp:"接続を待っています",en:"LINK OFFLINE",message:"Linuxホストへの再接続を続けています",code:"NET.91"},
};
function loadClapSettings(): ClapSettings { try { return { ...DEFAULT_CLAP_SETTINGS, ...JSON.parse(localStorage.getItem("clap-settings") || "{}"), hfMin:0.2, mode:"single" }; } catch { return { ...DEFAULT_CLAP_SETTINGS }; } }
function saveClapSettings(settings: ClapSettings) { try { localStorage.setItem("clap-settings", JSON.stringify(settings)); } catch { /* Safari private mode */ } }
function TelemetryCard({ label, value, suffix }: { label:string; value:string; suffix?:string }) { return <div className="telemetry-card"><span>{label}</span><strong>{value}</strong>{suffix ? <small>{suffix}</small> : null}</div>; }

export default function App() {
  const [state, setState] = useState<SecretaryState>("BOOTING");
  const [mic, setMic] = useState<"idle"|"on"|"denied">("idle");
  const [logs, setLogs] = useState<ClapLog[]>([]), [debug, setDebug] = useState(false);
  const [telemetry, setTelemetry] = useState<Telemetry>({ load:0, memory:0, uptime:"—", host:"JARVIS" });
  const [settings, setSettings] = useState<ClapSettings>(loadClapSettings);
  const socketRef = useRef<ReconnectingSocket|null>(null), stateRef = useRef(state); stateRef.current = state;
  const send = (event: SecretaryEvent) => setState(current => transition(current, event));
  const detector = useMemo(() => new ClapDetector(settings, () => { if (stateRef.current === "SLEEP") send("CLAP_DETECTED"); }, next => { setLogs(next); const last=next.at(-1); if(last) socketRef.current?.send({type:"clap.candidate",...last}); }), []);
  const microphone = useMemo(() => new ClapMicrophone(detector), [detector]);
  useEffect(() => { detector.update(settings); saveClapSettings(settings); }, [detector, settings]);
  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new ReconnectingSocket(`${protocol}://${location.host}/ws`, (status:SocketStatus) => { if(status==="open") send("CONNECTED"); else if(status==="closed") send("DISCONNECTED"); }, message => {
      if (!message || typeof message !== "object") return;
      const event = message as {type?:unknown;primary?:unknown;load?:unknown;memory?:unknown;uptime?:unknown;host?:unknown};
      if(event.type==="scheme.changed" && typeof event.primary==="string" && HEX.test(event.primary)) document.documentElement.style.setProperty("--tint",event.primary);
      if(event.type==="system.telemetry" && typeof event.load==="number" && typeof event.memory==="number") setTelemetry({load:event.load,memory:event.memory,uptime:String(event.uptime??"—"),host:String(event.host??"JARVIS")});
    });
    socketRef.current=socket; socket.start(); return()=>{socketRef.current=null;socket.stop();};
  },[]);
  useEffect(()=>{ if(state==="WAKING"){speechSynthesis.speak(new SpeechSynthesisUtterance("はい、どうしました？"));const id=setTimeout(()=>send("WAKE_FINISHED"),WAKE_ANIM_MS);return()=>clearTimeout(id);} if(state==="LISTENING"){const id=setTimeout(()=>send("IDLE"),LISTEN_IDLE_MS);return()=>clearTimeout(id);} if(state==="ERROR"){const id=setTimeout(()=>send("RETRY"),5000);return()=>clearTimeout(id);} },[state]);
  async function enableMic(){try{await microphone.start();setMic("on");}catch{setMic("denied");send("SYSTEM_ERROR");}}
  const params=import.meta.env.DEV||import.meta.env.VITE_PREVIEW==="1"?new URLSearchParams(location.search):null;
  const preview=params?.get("state")?.toUpperCase() as SecretaryState|undefined, view=preview&&preview in copy?preview:state, content=copy[view];
  const connected=!["BOOTING","OFFLINE","ERROR"].includes(view), showDebug=debug||params?.get("debug")==="1";
  return <main className={`shell state-${view.toLowerCase()}`}>
    <div className="atmosphere" aria-hidden="true"><i/><i/><i/></div><Secretary state={view}/>
    <section className="command-deck">
      <header className="masthead"><div className="brand"><b>JARVIS</b><span>PERSONAL INTELLIGENCE</span></div><div className="linux-mark"><span>CAELESTIA</span><strong>HYPRLAND // ARCH</strong></div></header>
      <div className="hero-copy"><div className="status-line"><span className={`signal ${connected?"online":""}`}/>{content.code} // {content.en}</div><h1>{content.jp}</h1><p>{content.message}</p></div>
      <div className="process-track"><span className="active">01&nbsp; WAKE</span><i/><span className={view!=="SLEEP"?"active":""}>02&nbsp; LISTEN</span><i/><span className={["THINKING","APPROVAL","SPEAKING"].includes(view)?"active":""}>03&nbsp; ACT</span></div>
      <section className="telemetry" aria-label="Linuxシステム情報"><TelemetryCard label="SYSTEM LOAD" value={telemetry.load.toFixed(2)} suffix="1 MIN"/><TelemetryCard label="MEMORY" value={`${Math.round(telemetry.memory)}`} suffix="% USED"/><TelemetryCard label="UPTIME" value={telemetry.uptime}/><TelemetryCard label="HOST" value={telemetry.host.toUpperCase()} suffix="LAN SECURE"/></section>
      <footer className="controls"><div className="live-copy"><span>{connected?"CORE ONLINE":"CORE PAUSED"}</span><small>VAULT LINK / LOCAL AI / NO CLOUD</small></div><div className="actions">{mic!=="on"?<button className="primary-action" onClick={enableMic}>音声回路を起動</button>:<span className="mic-live">● MIC LIVE</span>}{mic==="denied"?<span className="warning">MIC DENIED</span>:null}<button className="debug-action" onClick={()=>setDebug(value=>!value)}>{debug?"CLOSE LOG":"SYSTEM LOG"}</button></div></footer>
    </section><div className="edge-label" aria-hidden="true">INTELLIGENCE SYSTEM // 2026</div>{showDebug?<DebugPanel logs={logs} settings={settings} onSettings={setSettings}/>:null}
  </main>;
}
