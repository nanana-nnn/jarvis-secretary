import { useEffect, useMemo, useRef, useState } from "react";
import { ClapDetector } from "../audio/clap-detector";
import { ClapMicrophone } from "../audio/microphone";
import { ScreenWakeLock } from "../audio/wake-lock";
import { saveClapSettings } from "../clap-settings";
import type { ClapLog, ClapSettings } from "../audio/types";
import type { SecretaryState } from "../states/types";

const SNAP_TAIL_MS = 450;          // 拍手の余韻が消えるまで録音を待つ

export type MicStatus = "idle" | "on" | "denied";

export type MicHandlers = {
  /** 手拍子2回を検出した。起こすかどうかは呼び出し側が決める */
  onClap: () => void;
  /** 検出ログが増えた（DEBUG パネルとサーバーの調整ログ用） */
  onLogs: (logs: ClapLog[]) => void;
  /** マイクが止まって起こし直したときの報告。原因の切り分けに使う */
  onHealth: (report: Record<string, unknown>) => void;
  /** 録音した 16kHz PCM。送るかどうかは呼び出し側が決める */
  onAudio: (chunk: ArrayBuffer) => void;
};

/**
 * マイク・手拍子検出・画面ロックをまとめて持つ。
 *
 * 検出器とマイクは作り直さない（依存配列が空）ので、外から渡す処理は
 * ref 経由で最新を見る。作り直すと AudioWorklet を張り直すことになり、
 * 常設端末では音が数百ms途切れる。
 */
export function useMicrophone(settings: ClapSettings, state: SecretaryState, handlers: MicHandlers) {
  const [mic, setMic] = useState<MicStatus>("idle");
  // マイクが止まったまま起こせない状態。ユーザー操作が要るので画面に出す
  const [micStalled, setMicStalled] = useState(false);
  // 画面を消させない（常設端末なので寝ると手拍子も聞けない）
  const [awake, setAwake] = useState(false);
  const wakeLock = useMemo(() => new ScreenWakeLock(), []);

  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const detector = useMemo(() => new ClapDetector(
    settings,
    () => handlersRef.current.onClap(),
    next => handlersRef.current.onLogs(next),
  ), []);

  // 録音した 16kHz PCM は binary フレームで送る（DESIGN.md §8/§12）。
  // ただし送るのは §4 のとおり「会話中」だけ。待機中は手拍子の判定だけを
  // 端末で回す（detector はこのコールバックとは別に常時回っている）。
  // 常時送っていたため、エージェントが考えている20〜40秒のあいだにも音声が
  // 溜まり続け、接続が切れて STANDBY へ戻っていた（2026-09-01 実機）
  const microphone = useMemo(
    () => new ClapMicrophone(detector, chunk => handlersRef.current.onAudio(chunk)),
    [detector]);

  useEffect(() => { detector.update(settings); saveClapSettings(settings); }, [detector, settings]);

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
      handlersRef.current.onHealth({ ...microphone.health(), revived });
      if (revived) stalls = 0;
    }, 2000);
    return () => clearInterval(id);
  }, [microphone, mic]);

  /**
   * マイク許可を取る。失敗したら理由をそのまま返す
   * （2026-09-02、catch で握りつぶしていて「押しても何も起きない」の
   * 原因が見えなかった）。画面への出し方は呼び出し側が決める。
   */
  async function enable(): Promise<{ ok: true } | { ok: false; detail: string }> {
    try {
      await microphone.start();
      setMic("on");
      // 画面ロックの解除はユーザー操作の文脈でしか取れないことがある。
      // マイク許可と同じ操作のうちに取っておく
      setAwake(await wakeLock.enable());
      return { ok: true };
    } catch (error) {
      setMic("denied");
      return { ok: false, detail: error instanceof Error ? `${error.name}: ${error.message}` : String(error) };
    }
  }

  return { mic, micStalled, awake, microphone, enable };
}
