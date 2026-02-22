import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useVoiceSession } from "@/hooks/useVoiceSession";
import * as api from "@/lib/api";

// Mock ultravox-client
const mockJoinCall = vi.fn().mockResolvedValue(undefined);
const mockLeaveCall = vi.fn().mockResolvedValue(undefined);
const listeners: Record<string, Function> = {};

vi.mock("ultravox-client", () => ({
  UltravoxSession: vi.fn().mockImplementation(() => ({
    joinCall: mockJoinCall,
    leaveCall: mockLeaveCall,
    addEventListener: (event: string, cb: Function) => {
      listeners[event] = cb;
    },
    status: "idle",
    transcripts: [],
  })),
  UltravoxSessionStatus: {
    IDLE: "idle",
    CONNECTING: "connecting",
    LISTENING: "listening",
    THINKING: "thinking",
    SPEAKING: "speaking",
    DISCONNECTING: "disconnecting",
  },
}));

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(api.apiFetch);

describe("useVoiceSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(listeners).forEach((k) => delete listeners[k]);
  });

  it("starts in idle state", () => {
    const { result } = renderHook(() => useVoiceSession());
    expect(result.current.status).toBe("idle");
    expect(result.current.isActive).toBe(false);
    expect(result.current.transcripts).toEqual([]);
  });

  it("startSession calls API and joins call", async () => {
    mockApiFetch.mockResolvedValueOnce({
      call_id: "c1",
      join_url: "wss://join",
    });

    const { result } = renderHook(() => useVoiceSession());

    await act(async () => {
      await result.current.startSession();
    });

    expect(mockApiFetch).toHaveBeenCalledWith("/voice/start", {
      method: "POST",
    });
    expect(mockJoinCall).toHaveBeenCalledWith("wss://join");
    expect(result.current.isActive).toBe(true);
  });

  it("endSession calls leaveCall and API", async () => {
    mockApiFetch
      .mockResolvedValueOnce({ call_id: "c1", join_url: "wss://join" })
      .mockResolvedValueOnce({
        transcript: "Hello world",
        summary: "Greeting",
      });

    const { result } = renderHook(() => useVoiceSession());

    await act(async () => {
      await result.current.startSession();
    });

    let transcript: string | null = null;
    await act(async () => {
      transcript = await result.current.endSession();
    });

    expect(mockLeaveCall).toHaveBeenCalled();
    expect(transcript).toBe("Hello world");
    expect(result.current.isActive).toBe(false);
    expect(result.current.status).toBe("idle");
  });

  it("endSession returns null on API failure", async () => {
    mockApiFetch
      .mockResolvedValueOnce({ call_id: "c1", join_url: "wss://join" })
      .mockRejectedValueOnce(new Error("fail"));

    const { result } = renderHook(() => useVoiceSession());

    await act(async () => {
      await result.current.startSession();
    });

    let transcript: string | null = "not-null";
    await act(async () => {
      transcript = await result.current.endSession();
    });

    expect(transcript).toBeNull();
  });
});
