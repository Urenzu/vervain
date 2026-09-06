import type { RunMeta, RunRequest, ServerMessage, StateFrame } from "./protocol";

type Handlers = {
  onMeta?: (m: RunMeta) => void;
  onFrame?: (f: StateFrame) => void;
  onDone?: () => void;
  onStatus?: (s: ConnectionStatus) => void;
};

export type ConnectionStatus = "connecting" | "open" | "closed" | "error";

const URL = "ws://127.0.0.1:8765";

export class VervainClient {
  private ws: WebSocket | null = null;
  private handlers: Handlers = {};
  private pending: RunRequest | null = null;
  private retry: number | null = null;

  constructor(handlers: Handlers) {
    this.handlers = handlers;
    this.connect();
  }

  private connect() {
    this.handlers.onStatus?.("connecting");
    const ws = new WebSocket(URL);
    this.ws = ws;

    ws.onopen = () => {
      this.handlers.onStatus?.("open");
      if (this.pending) {
        ws.send(JSON.stringify(this.pending));
        this.pending = null;
      }
    };

    ws.onmessage = (ev) => {
      const msg: ServerMessage = JSON.parse(ev.data);
      if (msg.type === "meta") this.handlers.onMeta?.(msg);
      else if (msg.type === "frame") this.handlers.onFrame?.(msg);
      else if (msg.type === "done") this.handlers.onDone?.();
    };

    ws.onerror = () => this.handlers.onStatus?.("error");

    ws.onclose = () => {
      this.handlers.onStatus?.("closed");
      // The solver server takes a while to pre-warm on boot; keep retrying so the
      // page can be opened first without the user having to reload.
      if (this.retry === null) {
        this.retry = window.setTimeout(() => {
          this.retry = null;
          this.connect();
        }, 1500);
      }
    };
  }

  run(req: Omit<RunRequest, "type">) {
    const msg: RunRequest = { type: "run", ...req };
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      this.pending = msg;
    }
  }

  dispose() {
    if (this.retry !== null) window.clearTimeout(this.retry);
    this.ws?.close();
  }
}
