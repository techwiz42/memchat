"use client";

import { useState, useCallback, useRef } from "react";
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
  conversation_id?: string;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  // Use ref so sendMessage always reads the latest conversationId without re-creating the callback
  const conversationIdRef = useRef<string | null>(null);
  conversationIdRef.current = conversationId;

  const loadHistory = useCallback(async (convId?: string | null) => {
    try {
      const target = convId ?? null;
      let url = "/chat/history?limit=50";
      if (target) {
        url += `&conversation_id=${target}`;
      }
      const data = await apiFetch<ChatMessage[]>(url);
      setMessages(data);
    } catch (e) {
      console.error("Failed to load chat history:", e);
    }
  }, []);

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
      const currentConvId = conversationIdRef.current;
      const data = await apiFetch<{ response: string; conversation_id: string }>("/chat", {
        method: "POST",
        body: JSON.stringify({ message: text, conversation_id: currentConvId }),
      });

      // If a new conversation was created, store its id
      if (!currentConvId && data.conversation_id) {
        setConversationId(data.conversation_id);
        conversationIdRef.current = data.conversation_id;
      }

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
        const currentConvId = conversationIdRef.current;
        const formData = new FormData();
        formData.append("file", file);
        if (text) {
          formData.append("message", text);
        }
        if (currentConvId) {
          formData.append("conversation_id", currentConvId);
        }

        const data = await apiUpload<UploadResponse>(
          "/documents/upload",
          formData
        );

        // If a new conversation was created server-side, store its id
        if (!currentConvId && data.conversation_id) {
          setConversationId(data.conversation_id);
          conversationIdRef.current = data.conversation_id;
        }

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

  const newConversation = useCallback(() => {
    setConversationId(null);
    conversationIdRef.current = null;
    setMessages([]);
  }, []);

  const selectConversation = useCallback(async (id: string) => {
    setConversationId(id);
    await loadHistory(id);
  }, [loadHistory]);

  return {
    messages,
    loading,
    conversationId,
    sendMessage,
    sendMessageWithFile,
    appendVoiceTranscript,
    appendVisionAnalysis,
    loadHistory,
    newConversation,
    selectConversation,
  };
}
