import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  getAccessToken,
  getRefreshToken,
  setTokens,
  clearTokens,
  isLoggedIn,
  refreshAccessToken,
} from "@/lib/auth";

describe("auth token helpers", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe("getAccessToken / getRefreshToken", () => {
    it("returns null when nothing stored", () => {
      expect(getAccessToken()).toBeNull();
      expect(getRefreshToken()).toBeNull();
    });

    it("returns stored tokens", () => {
      setTokens("access-123", "refresh-456");
      expect(getAccessToken()).toBe("access-123");
      expect(getRefreshToken()).toBe("refresh-456");
    });
  });

  describe("setTokens / clearTokens", () => {
    it("stores and clears both tokens", () => {
      setTokens("a", "r");
      expect(getAccessToken()).toBe("a");
      clearTokens();
      expect(getAccessToken()).toBeNull();
      expect(getRefreshToken()).toBeNull();
    });
  });

  describe("isLoggedIn", () => {
    it("returns false when no token", () => {
      expect(isLoggedIn()).toBe(false);
    });

    it("returns true when access token exists", () => {
      setTokens("tok", "ref");
      expect(isLoggedIn()).toBe(true);
    });
  });

  describe("refreshAccessToken", () => {
    it("returns null if no refresh token", async () => {
      const result = await refreshAccessToken();
      expect(result).toBeNull();
    });

    it("refreshes and stores new tokens on success", async () => {
      setTokens("old-access", "old-refresh");

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "new-access",
            refresh_token: "new-refresh",
          }),
          { status: 200 }
        )
      );

      const result = await refreshAccessToken();
      expect(result).toBe("new-access");
      expect(getAccessToken()).toBe("new-access");
      expect(getRefreshToken()).toBe("new-refresh");
    });

    it("clears tokens on failed refresh", async () => {
      setTokens("old-access", "old-refresh");
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response("", { status: 401 })
      );

      const result = await refreshAccessToken();
      expect(result).toBeNull();
      expect(getAccessToken()).toBeNull();
    });

    it("clears tokens on network error", async () => {
      setTokens("old-access", "old-refresh");
      vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
        new Error("Network error")
      );

      const result = await refreshAccessToken();
      expect(result).toBeNull();
      expect(getAccessToken()).toBeNull();
    });
  });
});
