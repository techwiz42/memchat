"use client";

import { useState, useCallback, useRef } from "react";
import { UltravoxSession, UltravoxSessionStatus } from "ultravox-client";
import { apiFetch } from "@/lib/api";

export type VoiceStatus =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "disconnecting";

interface Transcript {
  speaker: "user" | "agent";
  text: string;
  isFinal: boolean;
}

export function useVoiceSession() {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [isActive, setIsActive] = useState(false);
  const sessionRef = useRef<UltravoxSession | null>(null);
  const callIdRef = useRef<string | null>(null);

  const startSession = useCallback(async () => {
    if (sessionRef.current) return;

    setStatus("connecting");
    setTranscripts([]);

    try {
      // Request call from backend
      const data = await apiFetch<{ call_id: string; join_url: string }>(
        "/voice/start",
        { method: "POST" }
      );

      callIdRef.current = data.call_id;

      // Create UltravoxSession and connect
      const session = new UltravoxSession();
      sessionRef.current = session;

      // Listen for status changes
      session.addEventListener("status", () => {
        const uvStatus = session.status;
        switch (uvStatus) {
          case UltravoxSessionStatus.IDLE:
            setStatus("idle");
            break;
          case UltravoxSessionStatus.CONNECTING:
            setStatus("connecting");
            break;
          case UltravoxSessionStatus.LISTENING:
            setStatus("listening");
            break;
          case UltravoxSessionStatus.THINKING:
            setStatus("thinking");
            break;
          case UltravoxSessionStatus.SPEAKING:
            setStatus("speaking");
            break;
          case UltravoxSessionStatus.DISCONNECTING:
            setStatus("disconnecting");
            break;
          default:
            break;
        }
      });

      // Listen for transcripts
      session.addEventListener("transcripts", () => {
        const allTranscripts = session.transcripts;
        setTranscripts(
          allTranscripts.map((t) => ({
            speaker: t.speaker === "user" ? "user" : "agent",
            text: t.text,
            isFinal: t.isFinal,
          }))
        );
      });

      await session.joinCall(data.join_url);
      setIsActive(true);
    } catch (e) {
      console.error("Failed to start voice session:", e);
      setStatus("idle");
      sessionRef.current = null;
      callIdRef.current = null;
      throw e;
    }
  }, []);

  const sendText = useCallback((text: string) => {
    const session = sessionRef.current;
    if (session) {
      session.sendText(text);
    }
  }, []);

  const endSession = useCallback(async (): Promise<string | null> => {
    const session = sessionRef.current;
    const callId = callIdRef.current;

    // Capture current transcripts before teardown
    const localTranscripts = [...transcripts];

    if (session) {
      setStatus("disconnecting");
      await session.leaveCall();
      sessionRef.current = null;
    }

    setIsActive(false);
    setStatus("idle");

    if (callId) {
      // Build a text transcript from the locally-captured stream as fallback
      const clientTranscript = localTranscripts
        .filter((t) => t.isFinal)
        .map((t) => `${t.speaker === "user" ? "User" : "Agent"}: ${t.text}`)
        .join("\n");

      try {
        const data = await apiFetch<{
          transcript: string | null;
          summary: string | null;
        }>("/voice/end", {
          method: "POST",
          body: JSON.stringify({
            call_id: callId,
            client_transcript: clientTranscript || null,
          }),
        });
        callIdRef.current = null;
        return data.transcript;
      } catch (e) {
        console.error("Failed to end voice session:", e);
      }
    }

    callIdRef.current = null;
    return null;
  }, [transcripts]);

  return {
    status,
    transcripts,
    isActive,
    startSession,
    endSession,
    sendText,
  };
}
