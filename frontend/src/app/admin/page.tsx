"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { apiFetch } from "@/lib/api";
import { isLoggedIn } from "@/lib/auth";

const ADMIN_EMAIL = "pete@cyberiad.ai";

interface SourceBreakdown {
  text: number;
  voice: number;
  vision: number;
}

interface DayCount {
  date: string;
  count: number;
}

interface UserStats {
  email: string;
  display_name: string | null;
  joined: string;
  messages: number;
  conversations: number;
  memories: number;
  voice_sessions: number;
  total_tokens: number;
  rag_bytes: number;
  last_active: string | null;
}

interface AdminStats {
  total_users: number;
  total_conversations: number;
  total_messages: number;
  total_memories: number;
  total_voice_sessions: number;
  total_tokens: number;
  total_rag_bytes: number;
  source_breakdown: SourceBreakdown;
  messages_per_day: DayCount[];
  users: UserStats[];
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const val = bytes / Math.pow(1024, i);
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export default function AdminPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (authLoading) return;
    if (!isLoggedIn() || !user) {
      router.replace("/login");
      return;
    }
    if (user.email !== ADMIN_EMAIL) {
      setLoading(false);
      return;
    }
    loadStats();
  }, [authLoading, user, router]);

  async function loadStats() {
    try {
      const data = await apiFetch<AdminStats>("/admin/stats");
      setStats(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load stats");
    } finally {
      setLoading(false);
    }
  }

  if (authLoading || loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="animate-spin w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!user || user.email !== ADMIN_EMAIL) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h1>
          <p className="text-gray-500 mb-4">You do not have admin access.</p>
          <button
            onClick={() => router.push("/chat")}
            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            Back to Chat
          </button>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <p className="text-red-600">{error}</p>
      </div>
    );
  }

  if (!stats) return null;

  const maxDayCount = Math.max(...stats.messages_per_day.map((d) => d.count), 1);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-semibold">Admin Dashboard</h1>
        <button
          onClick={() => router.push("/chat")}
          className="text-sm text-blue-600 hover:text-blue-800 font-medium"
        >
          Back to Chat
        </button>
      </header>

      <div className="max-w-5xl mx-auto py-8 px-4 space-y-8">
        {/* Aggregate stat cards */}
        <section>
          <h2 className="text-base font-semibold text-gray-900 mb-4">Platform Overview</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            <StatCard label="Users" value={stats.total_users.toLocaleString()} />
            <StatCard label="Conversations" value={stats.total_conversations.toLocaleString()} />
            <StatCard label="Messages" value={stats.total_messages.toLocaleString()} />
            <StatCard label="Memories" value={stats.total_memories.toLocaleString()} />
            <StatCard label="Voice Sessions" value={stats.total_voice_sessions.toLocaleString()} />
            <StatCard label="Total Tokens" value={formatTokens(stats.total_tokens)} />
            <StatCard label="RAG Storage" value={formatBytes(stats.total_rag_bytes)} />
          </div>
        </section>

        {/* Source breakdown */}
        <section>
          <h2 className="text-base font-semibold text-gray-900 mb-4">Messages by Source</h2>
          <div className="grid grid-cols-3 gap-4">
            <StatCard label="Text" value={stats.source_breakdown.text.toLocaleString()} />
            <StatCard label="Voice" value={stats.source_breakdown.voice.toLocaleString()} />
            <StatCard label="Vision" value={stats.source_breakdown.vision.toLocaleString()} />
          </div>
        </section>

        {/* Messages per day bar chart */}
        <section>
          <h2 className="text-base font-semibold text-gray-900 mb-4">Messages per Day (Last 30 Days)</h2>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            {stats.messages_per_day.length === 0 ? (
              <p className="text-sm text-gray-400">No messages in the last 30 days.</p>
            ) : (
              <div className="flex items-end gap-1" style={{ height: 160 }}>
                {stats.messages_per_day.map((d) => {
                  const pct = (d.count / maxDayCount) * 100;
                  return (
                    <div
                      key={d.date}
                      className="flex-1 group relative"
                      style={{ height: "100%" }}
                    >
                      <div className="absolute bottom-0 w-full rounded-t bg-blue-500 hover:bg-blue-600 transition-colors"
                        style={{ height: `${Math.max(pct, 2)}%` }}
                      />
                      <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs rounded px-2 py-1 opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-10">
                        {d.date}: {d.count}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>

        {/* Per-user table */}
        <section>
          <h2 className="text-base font-semibold text-gray-900 mb-4">Per-User Breakdown</h2>
          <div className="bg-white rounded-lg border border-gray-200 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-gray-500">
                  <th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Display Name</th>
                  <th className="px-4 py-3 font-medium text-right">Messages</th>
                  <th className="px-4 py-3 font-medium text-right">Convos</th>
                  <th className="px-4 py-3 font-medium text-right">Memories</th>
                  <th className="px-4 py-3 font-medium text-right">Voice</th>
                  <th className="px-4 py-3 font-medium text-right">Tokens</th>
                  <th className="px-4 py-3 font-medium text-right">RAG</th>
                  <th className="px-4 py-3 font-medium">Joined</th>
                  <th className="px-4 py-3 font-medium">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {stats.users.map((u) => (
                  <tr key={u.email} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-900">{u.email}</td>
                    <td className="px-4 py-3 text-gray-600">{u.display_name || "\u2014"}</td>
                    <td className="px-4 py-3 text-right font-medium text-gray-900">{u.messages.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{u.conversations.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{u.memories.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{u.voice_sessions.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{formatTokens(u.total_tokens)}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{formatBytes(u.rag_bytes)}</td>
                    <td className="px-4 py-3 text-gray-500">{u.joined}</td>
                    <td className="px-4 py-3 text-gray-500">{u.last_active || "\u2014"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-sm text-gray-500 mt-1">{label}</div>
    </div>
  );
}
