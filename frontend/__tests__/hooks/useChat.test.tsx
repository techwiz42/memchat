import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useChat } from "@/hooks/useChat";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

// Mock crypto.randomUUID for deterministic IDs
let uuidCounter = 0;
vi.stubGlobal("crypto", {
  randomUUID: () => `uuid-${++uuidCounter}`,
});

const mockApiFetch = vi.mocked(api.apiFetch);

describe("useChat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockApiFetch.mockReset();
    uuidCounter = 0;
    // Default: loadHistory returns empty
    mockApiFetch.mockResolvedValueOnce([]);
  });

  it("loads history on mount", async () => {
    mockApiFetch.mockReset();
    mockApiFetch.mockResolvedValueOnce([
      { id: "1", role: "user", content: "hi", source: "text", created_at: "2025-01-01" },
    ]);

    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0].content).toBe("hi");
  });

  it("sends message with optimistic update", async () => {
    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockApiFetch.mockResolvedValueOnce({ response: "Hello back!" });

    await act(async () => {
      await result.current.sendMessage("Hello");
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.messages[0].content).toBe("Hello");
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.messages[1].content).toBe("Hello back!");
  });

  it("adds error message on send failure", async () => {
    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockApiFetch.mockRejectedValueOnce(new Error("Network error"));

    await act(async () => {
      await result.current.sendMessage("failing");
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1].content).toContain("something went wrong");
  });

  it("appendVoiceTranscript adds voice message", async () => {
    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.appendVoiceTranscript("Voice text here");
    });

    expect(result.current.messages).toHaveLength(1);
    const msg = result.current.messages[0];
    expect(msg.role).toBe("assistant");
    expect(msg.source).toBe("voice");
    expect(msg.content).toContain("[Voice conversation]");
    expect(msg.content).toContain("Voice text here");
  });
});
