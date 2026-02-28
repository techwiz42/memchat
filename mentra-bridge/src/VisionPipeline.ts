import WebSocket from "ws";
import type { AppSession } from "@mentra/sdk";
import type { MemchatClient } from "./MemchatClient.js";
import type { VisionMessage } from "./types.js";

const CAPTURE_INTERVAL_MS = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;

export class VisionPipeline {
  private client: MemchatClient;
  private session: AppSession;
  private ws: WebSocket | null = null;
  private captureInterval: ReturnType<typeof setInterval> | null = null;
  private running = false;
  private reconnectAttempts = 0;

  constructor(client: MemchatClient, session: AppSession) {
    this.client = client;
    this.session = session;
  }

  async start(): Promise<void> {
    if (this.running) return;
    this.running = true;
    this.reconnectAttempts = 0;

    if (!this.session.capabilities?.camera) {
      console.warn("VisionPipeline: camera not available on this device");
      return;
    }

    await this.connect();
  }

  private async connect(): Promise<void> {
    if (!this.running) return;

    try {
      this.ws = await this.client.connectVisionWebSocket();
      this.reconnectAttempts = 0;
      console.log("VisionPipeline: WebSocket connected");

      this.ws.on("message", (data) => {
        try {
          const msg = JSON.parse(data.toString()) as VisionMessage;
          this.handleMessage(msg);
        } catch {
          console.warn("VisionPipeline: failed to parse WS message");
        }
      });

      this.ws.on("close", () => {
        console.log("VisionPipeline: WebSocket closed");
        this.stopCapture();
        this.reconnect();
      });

      this.ws.on("error", (err) => {
        console.error("VisionPipeline: WebSocket error:", err.message);
      });

      this.startCapture();
    } catch (err) {
      console.error("VisionPipeline: connection failed:", err);
      this.reconnect();
    }
  }

  private reconnect(): void {
    if (!this.running) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.error("VisionPipeline: max reconnection attempts reached");
      return;
    }

    const backoff = Math.min(
      BASE_BACKOFF_MS * Math.pow(2, this.reconnectAttempts),
      MAX_BACKOFF_MS
    );
    this.reconnectAttempts++;
    console.log(
      `VisionPipeline: reconnecting in ${backoff}ms (attempt ${this.reconnectAttempts})`
    );
    setTimeout(() => this.connect(), backoff);
  }

  private startCapture(): void {
    this.captureInterval = setInterval(() => {
      this.captureAndSend();
    }, CAPTURE_INTERVAL_MS);
  }

  private stopCapture(): void {
    if (this.captureInterval) {
      clearInterval(this.captureInterval);
      this.captureInterval = null;
    }
  }

  private async captureAndSend(): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    try {
      const photo = await this.session.camera.requestPhoto();
      this.client.sendVisionFrame(this.ws, photo.buffer);
    } catch (err) {
      console.error("VisionPipeline: capture failed:", err);
    }
  }

  private handleMessage(msg: VisionMessage): void {
    switch (msg.type) {
      case "detection": {
        const summary = Object.entries(msg.objects)
          .map(([obj, count]) => `${obj}: ${count}`)
          .join(", ");
        this.session.dashboard.content.write(summary);
        break;
      }
      case "analysis":
        this.session.layouts.showReferenceCard("I see", msg.content);
        break;
      case "error":
        console.error("VisionPipeline: server error:", msg.message);
        break;
    }
  }

  stop(): void {
    this.running = false;
    this.stopCapture();

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "stop" }));
      this.ws.close();
    }
    this.ws = null;
  }
}
