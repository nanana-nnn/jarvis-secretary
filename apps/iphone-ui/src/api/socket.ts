export type SocketStatus = "connecting" | "open" | "closed";

export class ReconnectingSocket {
  private socket?: WebSocket;
  private retry = 0;
  private timer?: number;
  private stopped = false;
  private heartbeat?: number;

  constructor(private readonly url: string, private readonly onStatus: (status: SocketStatus) => void) {}

  start(): void { this.stopped = false; this.connect(); }
  stop(): void { this.stopped = true; window.clearTimeout(this.timer); window.clearInterval(this.heartbeat); this.socket?.close(); }

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
    socket.addEventListener("close", () => {
      window.clearInterval(this.heartbeat);
      this.onStatus("closed");
      if (!this.stopped) this.timer = window.setTimeout(() => this.connect(), Math.min(1000 * 2 ** this.retry++, 30000));
    });
    socket.addEventListener("error", () => socket.close());
  }
}
