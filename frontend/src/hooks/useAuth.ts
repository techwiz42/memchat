"use client";

import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "@/lib/api";
import { setTokens, clearTokens, isLoggedIn } from "@/lib/auth";

interface User {
  id: string;
  email: string;
}

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    if (!isLoggedIn()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const data = await apiFetch<User>("/auth/me");
      setUser(data);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = useCallback(async (email: string, password: string) => {
    const data = await apiFetch<{
      access_token: string;
      refresh_token: string;
    }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setTokens(data.access_token, data.refresh_token);
    await fetchUser();
  }, [fetchUser]);

  const register = useCallback(async (email: string, password: string) => {
    const data = await apiFetch<{
      access_token: string;
      refresh_token: string;
    }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setTokens(data.access_token, data.refresh_token);
    await fetchUser();
  }, [fetchUser]);

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
  }, []);

  return { user, loading, login, register, logout };
}
