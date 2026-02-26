"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { setTokens } from "@/lib/auth";

export default function GoogleCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    // Tokens are in the URL fragment (#) so they never hit the server.
    const hash = window.location.hash.substring(1); // strip leading #
    const params = new URLSearchParams(hash);
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");

    if (accessToken && refreshToken) {
      setTokens(accessToken, refreshToken);
      // Clear tokens from URL immediately
      window.history.replaceState({}, "", "/auth/google/callback");
      router.replace("/chat");
    } else {
      router.replace("/login?error=missing_tokens");
    }
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="text-center">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-sm text-gray-500">Signing you in...</p>
      </div>
    </div>
  );
}
