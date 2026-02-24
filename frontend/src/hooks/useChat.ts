"use client";

import { useState, useCallback, useEffect } from "react";
import { apiFetch, apiUpload } from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  source: "text" | "voice" | "vision";
  created_at: string;
}

export interface UploadResponse {
  response: string;
  filename: string;
  chunks: number;
  extracted_text: string;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const data = await apiFetch<ChatMessage[]>("/chat/history?limit=50");
      setMessages(data);
    } catch (e) {
      console.error("Failed to load chat history:", e);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const sendMessage = useCallback(async (text: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      source: "text",
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const data = await apiFetch<{ response: string }>("/chat", {
        method: "POST",
        body: JSON.stringify({ message: text }),
      });

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.response,
        source: "text",
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e) {
      console.error("Chat error:", e);
      const errorMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "Sorry, something went wrong. Please try again.",
        source: "text",
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  }, []);

  const sendMessageWithFile = useCallback(
    async (text: string, file: File): Promise<UploadResponse | null> => {
      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: text
          ? `${text}\n[Uploaded document: ${file.name}]`
          : `[Uploaded document: ${file.name}]`,
        source: "text",
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);

      try {
        const formData = new FormData();
        formData.append("file", file);
        if (text) {
          formData.append("message", text);
        }

        const data = await apiUpload<UploadResponse>(
          "/documents/upload",
          formData
        );

        const assistantMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.response,
          source: "text",
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        return data;
      } catch (e) {
        console.error("Upload error:", e);
        const errorMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content:
            e instanceof Error
              ? `Upload failed: ${e.message}`
              : "Sorry, the upload failed. Please try again.",
          source: "text",
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errorMsg]);
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const appendVoiceTranscript = useCallback((transcript: string) => {
    // Parse "User: ..." / "Agent: ..." lines into separate ChatMessages
    const speakerRe = /^(User|Agent):\s*/gm;
    const parts: ChatMessage[] = [];
    const splits = transcript.split(speakerRe);
    // splits: [preamble?, "User", content, "Agent", content, ...]
    let i = 1;
    while (i + 1 < splits.length) {
      const speaker = splits[i];
      const content = splits[i + 1].trim();
      if (content) {
        parts.push({
          id: crypto.randomUUID(),
          role: speaker === "User" ? "user" : "assistant",
          content,
          source: "voice",
          created_at: new Date().toISOString(),
        });
      }
      i += 2;
    }
    // Fallback: if parsing produced nothing, show as single assistant message
    if (parts.length === 0) {
      parts.push({
        id: crypto.randomUUID(),
        role: "assistant",
        content: transcript.trim(),
        source: "voice",
        created_at: new Date().toISOString(),
      });
    }
    setMessages((prev) => [...prev, ...parts]);
  }, []);

  const appendVisionAnalysis = useCallback((description: string) => {
    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: description,
      source: "vision",
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, msg]);
  }, []);

  return {
    messages,
    loading,
    sendMessage,
    sendMessageWithFile,
    appendVoiceTranscript,
    appendVisionAnalysis,
    loadHistory,
  };
}
