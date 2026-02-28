import type { AppSession, TranscriptionData } from "@mentra/sdk";
import type { MemchatClient } from "./MemchatClient.js";
import type { TokenStore } from "./TokenStore.js";
import type { SessionState } from "./types.js";

const HUD_THROTTLE_MS = 200;

export class ChatPipeline {
  private client: MemchatClient;
  private tokenStore: TokenStore;
  private mentraUserId: string;
  private session: AppSession;
  private conversationId: string | null = null;
  private processing = false;
  private pendingTranscript: string | null = null;
  private onStateChange: (state: SessionState) => void;

  constructor(
    client: MemchatClient,
    tokenStore: TokenStore,
    mentraUserId: string,
    session: AppSession,
    onStateChange: (state: SessionState) => void
  ) {
    this.client = client;
    this.tokenStore = tokenStore;
    this.mentraUserId = mentraUserId;
    this.session = session;
    this.onStateChange = onStateChange;
  }

  async start(): Promise<void> {
    const mapping = await this.tokenStore.getUserMapping(this.mentraUserId);
    this.conversationId = mapping?.conversationId ?? null;

    this.session.events.onTranscription((data: TranscriptionData) => {
      this.handleTranscription(data.text, data.isFinal);
    });
  }

  private handleTranscription(text: string, isFinal: boolean): void {
    if (!isFinal) {
      this.session.layouts.showTextWall(text);
      return;
    }

    if (this.processing) {
      this.pendingTranscript = text;
      return;
    }

    this.processMessage(text).catch((err) => {
      console.error("ChatPipeline: processMessage error:", err);
      this.onStateChange("listening");
      this.processing = false;
    });
  }

  private async processMessage(text: string): Promise<void> {
    this.processing = true;
    this.onStateChange("thinking");
    this.session.dashboard.content.write("Thinking...");

    // Show user's message
    this.session.layouts.showReferenceCard("You", text);

    // Stream the response
    let fullResponse = "";
    let lastHudUpdate = 0;

    for await (const event of this.client.chatStream(
      text,
      this.conversationId
    )) {
      switch (event.type) {
        case "token":
          fullResponse += event.text;
          if (Date.now() - lastHudUpdate > HUD_THROTTLE_MS) {
            this.session.layouts.showTextWall(fullResponse);
            lastHudUpdate = Date.now();
          }
          break;

        case "content":
          fullResponse = event.text;
          break;

        case "progress":
          this.session.dashboard.content.write(event.message);
          break;

        case "done":
          this.conversationId = event.conversation_id;
          await this.tokenStore.updateConversationId(
            this.mentraUserId,
            event.conversation_id
          );
          break;

        case "error":
          console.error("ChatPipeline: stream error:", event.message);
          this.session.layouts.showReferenceCard("Error", event.message);
          break;
      }
    }

    // Show final response and speak it
    if (fullResponse) {
      this.session.layouts.showReferenceCard("Memchat", fullResponse);

      this.onStateChange("speaking");
      this.session.dashboard.content.write("Speaking");
      await this.session.audio.speak(fullResponse, {
        model_id: "eleven_flash_v2_5",
      });
    }

    this.processing = false;
    this.onStateChange("listening");
    this.session.dashboard.content.write("Listening");

    // Process any queued transcript
    if (this.pendingTranscript) {
      const pending = this.pendingTranscript;
      this.pendingTranscript = null;
      await this.processMessage(pending);
    }
  }

  async newConversation(): Promise<void> {
    this.conversationId = null;
    await this.tokenStore.updateConversationId(this.mentraUserId, "");
    this.session.layouts.showReferenceCard(
      "New Conversation",
      "Starting fresh"
    );
    await this.session.audio.speak("Starting a new conversation");
  }
}
