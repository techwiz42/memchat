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
