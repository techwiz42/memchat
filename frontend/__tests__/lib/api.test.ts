import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { apiFetch } from "@/lib/api";
import * as auth from "@/lib/auth";

// Mock window.location
const locationAssignMock = vi.fn();
Object.defineProperty(window, "location", {
  value: { href: "", assign: locationAssignMock },
  writable: true,
});

describe("apiFetch", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    window.location.href = "";
  });

  it("includes auth header when token exists", async () => {
    auth.setTokens("my-token", "ref");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );

    await apiFetch("/test");
    const [, init] = fetchSpy.mock.calls[0];
    expect((init?.headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer my-token"
    );
  });

  it("sets Content-Type to application/json", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 200 })
    );
    await apiFetch("/test");
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json"
    );
  });

  it("clears tokens and redirects on 401", async () => {
    auth.setTokens("tok", "ref");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", { status: 401 })
    );

    await expect(apiFetch("/secure")).rejects.toThrow("Unauthorized");
    expect(auth.getAccessToken()).toBeNull();
    expect(window.location.href).toBe("/login");
  });

  it("throws with detail message on error response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Bad request" }), { status: 400 })
    );

    await expect(apiFetch("/fail")).rejects.toThrow("Bad request");
  });

  it("throws generic message when no detail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("not json", { status: 500 })
    );

    await expect(apiFetch("/fail")).rejects.toThrow("API error: 500");
  });
});
