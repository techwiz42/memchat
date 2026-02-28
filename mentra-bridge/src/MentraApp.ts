import { AppServer, type AppSession } from "@mentra/sdk";
import type { Config } from "./config.js";
import type { TokenStore } from "./TokenStore.js";
import type { PairingManager } from "./PairingManager.js";
import { GlassesSession } from "./GlassesSession.js";

export class MentraApp extends AppServer {
  private bridgeConfig: Config;
  private tokenStore: TokenStore;
  private pairingManager: PairingManager;
  private glasses = new Map<string, GlassesSession>();

  constructor(
    config: Config,
    tokenStore: TokenStore,
    pairingManager: PairingManager
  ) {
    super({
      packageName: config.mentraPackageName,
      apiKey: config.mentraApiKey,
      port: config.port,
    });

    this.bridgeConfig = config;
    this.tokenStore = tokenStore;
    this.pairingManager = pairingManager;
  }

  protected override async onSession(
    session: AppSession,
    sessionId: string,
    userId: string
  ): Promise<void> {
    console.log(`MentraApp: new session ${sessionId} for user ${userId}`);

    const glassesSession = new GlassesSession(
      session,
      userId,
      this.bridgeConfig,
      this.tokenStore,
      this.pairingManager
    );

    this.glasses.set(sessionId, glassesSession);
    await glassesSession.initialize();
  }

  protected override async onStop(
    sessionId: string,
    userId: string,
    reason: string
  ): Promise<void> {
    console.log(
      `MentraApp: session ${sessionId} stopped for user ${userId}: ${reason}`
    );

    const glassesSession = this.glasses.get(sessionId);
    if (glassesSession) {
      glassesSession.destroy();
      this.glasses.delete(sessionId);
    }
  }
}
