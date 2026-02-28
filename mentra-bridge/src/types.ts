export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserMapping {
  memchatRefreshToken: string;
  memchatAccessToken: string;
  accessTokenExpiresAt: number; // unix timestamp ms
  conversationId: string | null;
}

export interface PairingRequest {
  mentraUserId: string;
  createdAt: number;
}

export type SessionState =
  | "unpaired"
  | "pairing"
  | "connected"
  | "listening"
  | "thinking"
  | "speaking";

// Memchat vision WebSocket messages
export interface VisionDetection {
  type: "detection";
  objects: Record<string, number>;
  frame: number;
}

export interface VisionAnalysis {
  type: "analysis";
  content: string;
  trigger: string;
}

export interface VisionError {
  type: "error";
  message: string;
}

export type VisionMessage = VisionDetection | VisionAnalysis | VisionError;

// Memchat chat SSE events
export interface ChatSSEToken {
  type: "token";
  text: string;
}

export interface ChatSSEProgress {
  type: "progress";
  message: string;
}

export interface ChatSSEContent {
  type: "content";
  text: string;
}

export interface ChatSSEDone {
  type: "done";
  conversation_id: string;
  history_tokens: number;
}

export interface ChatSSEError {
  type: "error";
  message: string;
}

export type ChatSSEEvent =
  | ChatSSEToken
  | ChatSSEProgress
  | ChatSSEContent
  | ChatSSEDone
  | ChatSSEError;
