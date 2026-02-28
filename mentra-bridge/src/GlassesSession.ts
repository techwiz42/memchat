import type { AppSession, ButtonPress } from "@mentra/sdk";
import type { Config } from "./config.js";
import type { TokenStore } from "./TokenStore.js";
import type { PairingManager } from "./PairingManager.js";
import { MemchatClient } from "./MemchatClient.js";
import { VisionPipeline } from "./VisionPipeline.js";
import { ChatPipeline } from "./ChatPipeline.js";
import type { SessionState } from "./types.js";

export class GlassesSession {
  private session: AppSession;
  private config: Config;
  private tokenStore: TokenStore;
  private pairingManager: PairingManager;
  private mentraUserId: string;

  private state: SessionState = "unpaired";
  private memchatClient: MemchatClient | null = null;
  private visionPipeline: VisionPipeline | null = null;
  private chatPipeline: ChatPipeline | null = null;

  constructor(
    session: AppSession,
    userId: string,
    config: Config,
    tokenStore: TokenStore,
    pairingManager: PairingManager
  ) {
    this.session = session;
    this.mentraUserId = userId;
    this.config = config;
    this.tokenStore = tokenStore;
    this.pairingManager = pairingManager;
  }

  async initialize(): Promise<void> {
    this.updateDashboard();

    // Button handler: short press = toggle listening, long press = new conversation
    this.session.events.onButtonPress((event: ButtonPress) => {
      this.handleButton(event);
    });

    // Check for existing pairing
    const mapping = await this.tokenStore.getUserMapping(this.mentraUserId);

    if (mapping) {
      await this.startConnected();
    } else {
      await this.startPairing();
    }
  }

  private async startPairing(): Promise<void> {
    this.setState("pairing");
    await this.pairingManager.startPairing(this.session, this.mentraUserId);

    const paired = await this.pairingManager.pollForCompletion(
      this.mentraUserId
    );

    if (paired) {
      this.session.layouts.showReferenceCard(
        "Paired",
        "Successfully connected to Memchat"
      );
      await this.session.audio.speak("Successfully paired with Memchat");
      await this.startConnected();
    } else {
      this.session.layouts.showReferenceCard(
        "Pairing Expired",
        "Please restart the app to try again"
      );
      this.setState("unpaired");
    }
  }

  private async startConnected(): Promise<void> {
    this.setState("connected");

    this.memchatClient = new MemchatClient(
      this.mentraUserId,
      this.tokenStore,
      this.config
    );

    // Start vision pipeline
    this.visionPipeline = new VisionPipeline(this.memchatClient, this.session);
    await this.visionPipeline.start();

    // Start chat pipeline
    this.chatPipeline = new ChatPipeline(
      this.memchatClient,
      this.tokenStore,
      this.mentraUserId,
      this.session,
      (newState) => this.setState(newState)
    );
    await this.chatPipeline.start();

    this.setState("listening");
    this.session.layouts.showReferenceCard(
      "Ready",
      "Memchat is listening. Speak to chat."
    );
  }

  private handleButton(event: ButtonPress): void {
    if (event.pressType === "short") {
      // New conversation
      if (this.chatPipeline) {
        this.chatPipeline.newConversation();
      }
    } else if (event.pressType === "long") {
      // Show status
      this.showStatus();
    }
  }

  private showStatus(): void {
    const statusLines = [
      `State: ${this.state}`,
      `User: ${this.mentraUserId}`,
    ];
    this.session.layouts.showReferenceCard("Status", statusLines.join("\n"));
  }

  private setState(state: SessionState): void {
    this.state = state;
    this.updateDashboard();
  }

  private updateDashboard(): void {
    this.session.dashboard.content.write(this.state);
  }

  destroy(): void {
    if (this.visionPipeline) {
      this.visionPipeline.stop();
      this.visionPipeline = null;
    }
    this.chatPipeline = null;
    this.memchatClient = null;
    this.setState("unpaired");
  }
}
