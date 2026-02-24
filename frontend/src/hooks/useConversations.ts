"use client";

import { useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";

export interface ConversationItem {
  id: string;
  title: string;
  summary: string | null;
  created_at: string;
  updated_at: string;
}

export function useConversations() {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);

  const loadConversations = useCallback(async () => {
    try {
      const data = await apiFetch<ConversationItem[]>("/conversations");
      setConversations(data);
    } catch (e) {
      console.error("Failed to load conversations:", e);
    }
  }, []);

  const deleteConversation = useCallback(async (id: string) => {
    try {
      await apiFetch(`/conversations/${id}`, { method: "DELETE" });
      setConversations((prev) => prev.filter((c) => c.id !== id));
    } catch (e) {
      console.error("Failed to delete conversation:", e);
    }
  }, []);

  return {
    conversations,
    loadConversations,
    deleteConversation,
  };
}
