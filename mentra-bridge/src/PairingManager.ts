import { randomInt } from "node:crypto";
import type { AppSession } from "@mentra/sdk";
import type { TokenStore } from "./TokenStore.js";
import type { Config } from "./config.js";

export class PairingManager {
  private tokenStore: TokenStore;
  private config: Config;

  constructor(tokenStore: TokenStore, config: Config) {
    this.tokenStore = tokenStore;
    this.config = config;
  }

  async startPairing(
    session: AppSession,
    mentraUserId: string
  ): Promise<string> {
    const code = String(randomInt(100000, 999999));
    await this.tokenStore.storePairingCode(code, mentraUserId);

    const pairUrl = `${this.config.pairingBaseUrl}/pair`;
    const message = `Visit ${pairUrl} and enter code ${code}`;

    session.layouts.showTextWall(message);
    session.audio.speak(
      `To pair your glasses, visit ${pairUrl} on your phone and enter code ${code.split("").join(" ")}`
    );

    return code;
  }

  async pollForCompletion(
    mentraUserId: string,
    timeoutMs: number = 300_000
  ): Promise<boolean> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const mapping = await this.tokenStore.getUserMapping(mentraUserId);
      if (mapping) return true;
      await sleep(2000);
    }
    return false;
  }

  async handlePairRequest(
    code: string,
    email: string,
    password: string
  ): Promise<{ success: boolean; error?: string }> {
    const pairingRequest = await this.tokenStore.consumePairingCode(code);
    if (!pairingRequest) {
      return { success: false, error: "Invalid or expired pairing code" };
    }

    const resp = await fetch(`${this.config.memchatBaseUrl}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!resp.ok) {
      const body = (await resp.json().catch(() => ({}))) as Record<
        string,
        string
      >;
      return {
        success: false,
        error: body.detail ?? `Authentication failed (${resp.status})`,
      };
    }

    const tokens = (await resp.json()) as {
      access_token: string;
      refresh_token: string;
    };

    await this.tokenStore.storeUserMapping(pairingRequest.mentraUserId, {
      memchatAccessToken: tokens.access_token,
      memchatRefreshToken: tokens.refresh_token,
      accessTokenExpiresAt: Date.now() + 60 * 60 * 1000,
      conversationId: null,
    });

    return { success: true };
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
