import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAuth } from "@/hooks/useAuth";
import * as auth from "@/lib/auth";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(api.apiFetch);

describe("useAuth", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    mockApiFetch.mockReset();
  });

  it("fetches user on mount when logged in", async () => {
    auth.setTokens("tok", "ref");
    mockApiFetch.mockResolvedValueOnce({ id: "u1", email: "a@b.com" });

    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toEqual({ id: "u1", email: "a@b.com" });
  });

  it("sets user to null when not logged in", async () => {
    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
  });

  it("login stores tokens and fetches user", async () => {
    mockApiFetch
      .mockResolvedValueOnce({
        access_token: "new-acc",
        refresh_token: "new-ref",
      })
      .mockResolvedValueOnce({ id: "u2", email: "user@test.com" });

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.login("user@test.com", "pass");
    });

    expect(auth.getAccessToken()).toBe("new-acc");
    expect(result.current.user?.email).toBe("user@test.com");
  });

  it("register stores tokens and fetches user", async () => {
    mockApiFetch
      .mockResolvedValueOnce({
        access_token: "reg-acc",
        refresh_token: "reg-ref",
      })
      .mockResolvedValueOnce({ id: "u3", email: "new@test.com" });

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.register("new@test.com", "pass123");
    });

    expect(auth.getAccessToken()).toBe("reg-acc");
    expect(result.current.user?.email).toBe("new@test.com");
  });

  it("logout clears tokens and user", async () => {
    auth.setTokens("tok", "ref");
    mockApiFetch.mockResolvedValueOnce({ id: "u1", email: "a@b.com" });

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.user).not.toBeNull());

    act(() => {
      result.current.logout();
    });

    expect(result.current.user).toBeNull();
    expect(auth.getAccessToken()).toBeNull();
  });
});
