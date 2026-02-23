"use client";

import { useState, useCallback, useEffect } from "react";
import { apiFetch, apiUpload } from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  source: "text" | "voice";
  created_at: string;
}

interface UploadResponse {
  response: string;
  filename: string;
  chunks: number;
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
    async (text: string, file: File) => {
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
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const appendVoiceTranscript = useCallback((transcript: string) => {
    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: `[Voice conversation]\n${transcript}`,
      source: "voice",
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
    loadHistory,
  };
}
