/**
 * HTTP client with JWT auth headers.
 * All API calls go through the nginx proxy at /api/*.
 */

import { getAccessToken, clearTokens } from "./auth";

const API_BASE = "/api";

interface FetchOptions extends Omit<RequestInit, "headers"> {
  headers?: Record<string, string>;
}

export async function apiFetch<T = any>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    clearTokens();
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${response.status}`);
  }

  return response.json();
}

export interface StreamCallbacks {
  onProgress?: (message: string) => void;
  onContent?: (text: string) => void;
  onDone?: (conversationId: string, historyTokens?: number) => void;
  onError?: (error: string) => void;
}

/**
 * Stream SSE events from a POST endpoint.
 * Returns an AbortController so the caller can cancel the stream.
 */
export function apiStream(
  path: string,
  body: Record<string, unknown>,
  callbacks: StreamCallbacks,
): AbortController {
  const controller = new AbortController();
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  (async () => {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (response.status === 401) {
        clearTokens();
        window.location.href = "/login";
        return;
      }

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}));
        callbacks.onError?.(errBody.detail || `API error: ${response.status}`);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        callbacks.onError?.("No response body");
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        // Keep the last (possibly incomplete) line in the buffer
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data: ")) continue;
          const jsonStr = trimmed.slice(6);
          try {
            const event = JSON.parse(jsonStr);
            switch (event.type) {
              case "progress":
                callbacks.onProgress?.(event.message);
                break;
              case "content":
                callbacks.onContent?.(event.text);
                break;
              case "done":
                callbacks.onDone?.(event.conversation_id, event.history_tokens);
                break;
              case "error":
                callbacks.onError?.(event.message);
                break;
            }
          } catch {
            // skip malformed JSON lines
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      callbacks.onError?.(err instanceof Error ? err.message : "Stream failed");
    }
  })();

  return controller;
}

export async function apiUpload<T = any>(
  path: string,
  formData: FormData
): Promise<T> {
  const token = getAccessToken();
  const headers: Record<string, string> = {};

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  // Do NOT set Content-Type — browser sets multipart boundary automatically
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (response.status === 401) {
    clearTokens();
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${response.status}`);
  }

  return response.json();
}
