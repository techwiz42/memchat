"use client";

import { useState, useCallback, useRef } from "react";
import { apiFetch, apiUpload, apiStream } from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  source: "text" | "voice" | "vision";
  created_at: string;
  streaming?: boolean;
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
  const [historyTokens, setHistoryTokens] = useState<number | null>(null);
  const [progressLines, setProgressLines] = useState<string[]>([]);
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
    const placeholderId = crypto.randomUUID();
    const placeholderMsg: ChatMessage = {
      id: placeholderId,
      role: "assistant",
      content: "",
      source: "text",
      created_at: new Date().toISOString(),
      streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, placeholderMsg]);
    setLoading(true);
    setProgressLines([]);

    const currentConvId = conversationIdRef.current;

    apiStream(
      "/chat/stream",
      { message: text, conversation_id: currentConvId },
      {
        onToken(text) {
          setMessages((prev) => prev.map((m) =>
            m.id === placeholderId ? { ...m, content: m.content + text } : m
          ));
        },
        onProgress(message) {
          setProgressLines((prev) => [...prev, message]);
        },
        onContent(finalText) {
          setProgressLines([]);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === placeholderId ? { ...m, content: finalText, streaming: false } : m,
            ),
          );
        },
        onDone(convId, tokens) {
          if (!currentConvId && convId) {
            setConversationId(convId);
            conversationIdRef.current = convId;
          }
          if (tokens !== undefined) {
            setHistoryTokens(tokens);
          }
          setLoading(false);
        },
        onError(error) {
          console.error("Stream error:", error);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === placeholderId
                ? { ...m, content: "Sorry, something went wrong. Please try again.", streaming: false }
                : m,
            ),
          );
          setLoading(false);
        },
      },
    );
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

  const editMessage = useCallback(async (id: string, newContent: string) => {
    // Update the message content on the backend
    await apiFetch(`/chat/messages/${id}`, {
      method: "PUT",
      body: JSON.stringify({ content: newContent }),
    });
    // Update local state
    setMessages((prev) => prev.map((m) =>
      m.id === id ? { ...m, content: newContent } : m
    ));
    // Now regenerate from that message
    regenerateAfter(id);
  }, []);

  const regenerateAfter = useCallback((messageId: string) => {
    // Find the user message to regenerate from
    const msgIndex = messages.findIndex((m) => m.id === messageId);
    if (msgIndex === -1) return;
    const userMsg = messages[msgIndex];

    // For assistant messages, find the preceding user message
    let targetMsg = userMsg;
    if (userMsg.role === "assistant") {
      for (let i = msgIndex - 1; i >= 0; i--) {
        if (messages[i].role === "user") {
          targetMsg = messages[i];
          break;
        }
      }
    }

    // Remove messages after the target user message and add placeholder
    const targetIndex = messages.findIndex((m) => m.id === targetMsg.id);
    const placeholderId = crypto.randomUUID();
    const placeholderMsg: ChatMessage = {
      id: placeholderId,
      role: "assistant",
      content: "",
      source: "text",
      created_at: new Date().toISOString(),
      streaming: true,
    };
    setMessages((prev) => [...prev.slice(0, targetIndex + 1), placeholderMsg]);
    setLoading(true);
    setProgressLines([]);

    apiStream(
      "/chat/regenerate",
      { message_id: targetMsg.id },
      {
        onToken(text) {
          setMessages((prev) => prev.map((m) =>
            m.id === placeholderId ? { ...m, content: m.content + text } : m
          ));
        },
        onProgress(message) {
          setProgressLines((prev) => [...prev, message]);
        },
        onContent(finalText) {
          setProgressLines([]);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === placeholderId ? { ...m, content: finalText, streaming: false } : m
            ),
          );
        },
        onDone(_convId, tokens) {
          if (tokens !== undefined) {
            setHistoryTokens(tokens);
          }
          setLoading(false);
        },
        onError(error) {
          console.error("Regenerate error:", error);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === placeholderId
                ? { ...m, content: "Sorry, regeneration failed. Please try again.", streaming: false }
                : m
            ),
          );
          setLoading(false);
        },
      },
    );
  }, [messages]);

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
    historyTokens,
    progressLines,
    sendMessage,
    sendMessageWithFile,
    appendVoiceTranscript,
    appendVisionAnalysis,
    loadHistory,
    newConversation,
    selectConversation,
    editMessage,
    regenerateAfter,
  };
}
