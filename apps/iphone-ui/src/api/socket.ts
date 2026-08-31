export type SocketStatus = "connecting" | "open" | "closed";

export class ReconnectingSocket {
  private socket?: WebSocket;
  private retry = 0;
  private timer?: number;
  private stopped = false;
  private heartbeat?: number;

  constructor(
    private readonly url: string,
    private readonly onStatus: (status: SocketStatus) => void,
    private readonly onMessage?: (message: unknown) => void,
  ) {}

  start(): void { this.stopped = false; this.connect(); }
  stop(): void { this.stopped = true; window.clearTimeout(this.timer); window.clearInterval(this.heartbeat); this.socket?.close(); }
  send(message: object): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(message));
    return true;
  }

  /**
   * 音声チャンクを binary フレームで送る（DESIGN.md §12）。
   * 詰まっているときは捨てる。溜めても書き起こしは遅れるだけで、
   * 古い音を後から送っても会話にならない。
   */
  sendAudio(chunk: ArrayBuffer): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    if (this.socket.bufferedAmount > 1 << 18) return false;   // 256KB 以上溜まったら捨てる
    this.socket.send(chunk);
    return true;
  }

  private connect(): void {
    if (this.stopped) return;
    this.onStatus("connecting");
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.addEventListener("open", () => {
      this.retry = 0;
      this.onStatus("open");
      this.heartbeat = window.setInterval(() => socket.readyState === WebSocket.OPEN && socket.send(JSON.stringify({ type: "connection.ping" })), 15000);
    });
    socket.addEventListener("message", event => {
      try { this.onMessage?.(JSON.parse(String(event.data))); } catch { /* Ignore malformed server events. */ }
    });
    socket.addEventListener("close", () => {
      window.clearInterval(this.heartbeat);
      if (this.stopped || this.socket !== socket) return;
      this.onStatus("closed");
      this.timer = window.setTimeout(() => this.connect(), Math.min(1000 * 2 ** this.retry++, 30000));
    });
    socket.addEventListener("error", () => socket.close());
  }
}
