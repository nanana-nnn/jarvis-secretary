import { useEffect, useRef } from "react";
import { ReconnectingSocket, type SocketStatus } from "../api/socket";
import { applyScheme, applyWallpaper } from "../theme";
import type { WallpaperChoice } from "../components/WallpaperPicker";
import type { LiveFacts } from "../components/Live";
import type { Approval, Telemetry } from "../model";
import type { SecretaryEvent } from "../states/types";

/**
 * サーバーとの WebSocket（DESIGN.md §12）。
 *
 * 受け取ったイベントを画面の操作へ振り分けるだけで、状態は持たない。
 * 接続は一度だけ張る（依存配列が空）ので、渡された操作は ref 経由で
 * 最新を見る。張り直すと再接続のたびに常設端末が STANDBY へ戻る。
 */
export type SocketActions = {
  send: (event: SecretaryEvent) => void;
  setCaption: (text: string) => void;
  setSpeaking: (value: boolean) => void;
  setHeardNothingAt: (at: number) => void;
  setPapers: (items: WallpaperChoice[] | null) => void;
  setApplyingPaper: (id: string | null) => void;
  setApproval: (approval: Approval | null) => void;
  setLive: (update: (previous: LiveFacts) => LiveFacts) => void;
  setTelemetry: (update: (previous: Telemetry) => Telemetry) => void;
  qaUpdate: (patch: { question?: string; phase?: "listening" | "thinking" | "done" }) => void;
  qaAddLine: (line: string) => void;
  qaAddLines: (lines: string[]) => void;
};

export function useSecretarySocket(actions: SocketActions) {
  const socketRef = useRef<ReconnectingSocket | null>(null);
  const actionsRef = useRef(actions);
  actionsRef.current = actions;

  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new ReconnectingSocket(
      `${protocol}://${location.host}/ws`,
      (status: SocketStatus) => {
        if (status === "open") actionsRef.current.send("CONNECTED");
        else if (status === "closed") actionsRef.current.send("DISCONNECTED");
      },
      message => {
        if (!message || typeof message !== "object") return;
        handle(message as Record<string, unknown>, actionsRef.current);
      },
    );
    socketRef.current = socket;
    socket.start();
    return () => { socketRef.current = null; socket.stop(); };
  }, []);

  return socketRef;
}

function handle(event: Record<string, unknown>, actions: SocketActions): void {
  switch (event.type) {
    // 壁紙を替えると caelestia の scheme.json が作り直され、
    // mode と必要な Material token 一式が届く
    case "scheme.changed":
      applyScheme(event.scheme);
      return;

    case "wallpaper.changed":
      applyWallpaper(event.version);
      return;

    // 「壁紙かえたい」への返事。1段目をスライダーへ差し替える
    case "wallpaper.choices":
      if (!Array.isArray(event.items)) return;
      actions.setPapers(event.items as WallpaperChoice[]);
      actions.setApplyingPaper(null);
      actions.setCaption("どれにする？");
      actions.send("AGENT_COMPLETED");   // TRANSCRIBING/THINKING に留まらせない
      return;

    // 切り替えの結果。**成功したらスライダーを閉じて元のカードへ戻す**
    // （本人の指定：変わったら元に戻る）。実際の見た目の反映は
    // wallpaper.changed / scheme.changed が別途届いて行う
    case "wallpaper.applied":
      actions.setApplyingPaper(null);
      if (event.ok) {
        actions.setPapers(null);
        actions.setCaption("壁紙を変えたよ");
        actions.send("IDLE");
      } else {
        actions.setCaption("壁紙を変えられなかった");
      }
      return;

    // 答えを作り始めた。時間がかかるので画面で分かるようにする（§12）
    case "agent.started":
      actions.qaUpdate({ phase: "thinking" });
      // 分単位かかる用件は、待ち時間の見当と止め方を最初に見せる。
      // 黙って何分も待たせないための約束（2026-09-02）
      if (event.long) actions.qaAddLine("取りかかります。数分かかります。「やめて」で止まります。");
      actions.send("AGENT_STARTED");
      return;

    // 経過。長い仕事のあいだ、生きていることを見せ続ける
    case "agent.progress": {
      const elapsed = typeof event.elapsed === "number" ? event.elapsed : 0;
      actions.qaAddLine(`作業中… ${Math.floor(elapsed / 60)}分${String(elapsed % 60).padStart(2, "0")}秒`);
      return;
    }

    // 「やめて」で止めた。カードへ表示してから待機へ戻れる状態にする
    case "agent.cancelled":
      actions.qaAddLine("止めました。");
      actions.qaUpdate({ phase: "done" });
      actions.send("IDLE");
      return;

    // 答えが出た。文字回答カードへ追加表示する（読み上げは廃止・2026-09-02）
    case "agent.completed": {
      const summary = typeof event.summary === "string" && event.summary ? event.summary
        : typeof event.spoken_reply === "string" ? event.spoken_reply : "";
      const lines = summary.split("\n").map(line => line.trim()).filter(Boolean);
      actions.qaAddLines(lines.length ? lines : ["（答えが空でした）"]);
      actions.qaUpdate({ phase: "done" });
      actions.send("AGENT_COMPLETED");
      return;
    }

    // Phase 4: display the exact proposed files and diff before the real
    // Vault can be touched.  Approval itself is a separate HTTP request.
    case "approval.required": {
      if (typeof event.job_id !== "string") return;
      actions.setApproval({
        id: event.job_id,
        summary: typeof event.summary === "string" ? event.summary : "",
        files: Array.isArray(event.changed_files) ? event.changed_files.filter((file): file is string => typeof file === "string") : [],
        diff: typeof event.diff === "string" ? event.diff : "",
        // §11-3 対象が既に dirty なら承認前に見せる。押す前に読めないと意味がない
        warnings: Array.isArray(event.warnings) ? event.warnings.filter((line): line is string => typeof line === "string") : [],
      });
      actions.setCaption("CHANGE REVIEW REQUIRED");
      actions.qaAddLine("確認をお願いします（下の画面で承認／却下）。");
      actions.send("APPROVAL_REQUIRED");
      return;
    }

    // 待機へ戻す指示（「ありがとう」など §9 の SYSTEM）
    case "session.sleep":
      actions.send("IDLE");
      return;

    // 話し始めた。待機へ戻るタイマーを止める（§8 の VAD による検出）
    case "audio.speaking":
      actions.setSpeaking(true);
      return;

    // 聞き取りが確定した（§12 audio.final）。「続けて聞く」で開いた
    // 空の質問行をここで埋める（拍手起動の固定質問はこの経路を通らない）
    case "audio.final":
      if (typeof event.text !== "string") return;
      actions.setCaption(event.text);
      actions.qaUpdate({ question: event.text, phase: "thinking" });
      actions.send("AUDIO_FINAL");
      return;

    // 書き起こしに失敗した。黙って戻らず理由を出す（§17）
    case "system.error": {
      const message = typeof event.message === "string" ? event.message : "";
      if (event.code === "STT_FAILED") {
        // その場では寝ない。拍手の余韻で空振りすることがあり、
        // 即座に寝ると話しかける前に落ちる。文言を見せてから少し待って戻す
        actions.setCaption(message || "聞き取れませんでした");
        actions.qaAddLine(message || "聞き取れませんでした");
        actions.qaUpdate({ phase: "done" });
        actions.setHeardNothingAt(Date.now());
      } else {
        actions.setCaption(message);
        actions.qaAddLine(message);
        actions.qaUpdate({ phase: "done" });
        actions.send("SYSTEM_ERROR");
      }
      return;
    }

    // 3段目の実測（5秒間隔）。形が違うものは捨てて、前の値を残す
    case "system.live":
      if (!event.apps || typeof event.apps !== "object") return;
      actions.setLive(previous => ({
        apps: event.apps as LiveFacts["apps"],
        vault: (event.vault && typeof event.vault === "object" ? event.vault : previous.vault) as LiveFacts["vault"],
        phones: typeof event.phones === "number" ? event.phones : previous.phones,
      }));
      return;

    // PC の実測値（5秒間隔）。届いた項目だけ差し替え、欠けていれば前の値を残す
    case "system.telemetry": {
      const text = (key: string, fallback: string) => typeof event[key] === "string" ? event[key] as string : fallback;
      actions.setTelemetry(previous => ({
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
      return;
    }
  }
}
