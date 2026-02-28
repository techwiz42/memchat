import WebSocket from "ws";
import type { Config } from "./config.js";
import type { TokenStore } from "./TokenStore.js";
import type { ChatSSEEvent } from "./types.js";

const TOKEN_REFRESH_BUFFER_MS = 5 * 60 * 1000; // refresh 5 min before expiry

export class MemchatClient {
  private mentraUserId: string;
  private tokenStore: TokenStore;
  private baseUrl: string;
  private wsUrl: string;

  constructor(
    mentraUserId: string,
    tokenStore: TokenStore,
    config: Config
  ) {
    this.mentraUserId = mentraUserId;
    this.tokenStore = tokenStore;
    this.baseUrl = config.memchatBaseUrl;
    this.wsUrl = config.memchatWsUrl;
  }

  async getAccessToken(): Promise<string> {
    const mapping = await this.tokenStore.getUserMapping(this.mentraUserId);
    if (!mapping) {
      throw new Error("User not paired — no mapping found");
    }

    if (Date.now() < mapping.accessTokenExpiresAt - TOKEN_REFRESH_BUFFER_MS) {
      return mapping.memchatAccessToken;
    }

    return this.refreshAccessToken();
  }

  async refreshAccessToken(): Promise<string> {
    const mapping = await this.tokenStore.getUserMapping(this.mentraUserId);
    if (!mapping) {
      throw new Error("User not paired — no mapping found");
    }

    const resp = await fetch(`${this.baseUrl}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: mapping.memchatRefreshToken }),
    });

    if (!resp.ok) {
      if (resp.status === 401) {
        await this.tokenStore.removeUserMapping(this.mentraUserId);
        throw new Error("Refresh token expired — user must re-pair");
      }
      throw new Error(`Token refresh failed: ${resp.status} ${resp.statusText}`);
    }

    const data = (await resp.json()) as {
      access_token: string;
      refresh_token: string;
    };

    // Access tokens are 60 minutes in the backend
    const expiresAt = Date.now() + 60 * 60 * 1000;
    await this.tokenStore.storeUserMapping(this.mentraUserId, {
      memchatAccessToken: data.access_token,
      memchatRefreshToken: data.refresh_token,
      accessTokenExpiresAt: expiresAt,
      conversationId: mapping.conversationId,
    });

    return data.access_token;
  }

  async *chatStream(
    message: string,
    conversationId?: string | null
  ): AsyncGenerator<ChatSSEEvent> {
    const token = await this.getAccessToken();

    const body: Record<string, string> = { message };
    if (conversationId) body.conversation_id = conversationId;

    const resp = await fetch(`${this.baseUrl}/api/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });

    if (resp.status === 401) {
      // Try one refresh then retry
      const newToken = await this.refreshAccessToken();
      const retryResp = await fetch(`${this.baseUrl}/api/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${newToken}`,
        },
        body: JSON.stringify(body),
      });
      if (!retryResp.ok) {
        throw new Error(`Chat stream failed after refresh: ${retryResp.status}`);
      }
      yield* this.parseSSEStream(retryResp);
      return;
    }

    if (!resp.ok) {
      throw new Error(`Chat stream failed: ${resp.status} ${resp.statusText}`);
    }

    yield* this.parseSSEStream(resp);
  }

  private async *parseSSEStream(
    resp: Response
  ): AsyncGenerator<ChatSSEEvent> {
    const reader = resp.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith("data: ")) continue;

        const jsonStr = trimmed.slice(6);
        if (jsonStr === "[DONE]") return;

        try {
          const event = JSON.parse(jsonStr) as ChatSSEEvent;
          yield event;
        } catch {
          console.warn("Failed to parse SSE event:", jsonStr);
        }
      }
    }
  }

  connectVisionWebSocket(): Promise<WebSocket> {
    return new Promise(async (resolve, reject) => {
      let token: string;
      try {
        token = await this.getAccessToken();
      } catch (err) {
        reject(err);
        return;
      }

      const url = `${this.wsUrl}/api/vision/stream?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(url);

      ws.once("open", () => resolve(ws));
      ws.once("error", (err) => reject(err));
    });
  }

  sendVisionFrame(ws: WebSocket, buffer: Buffer): void {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(buffer);
    }
  }
}
