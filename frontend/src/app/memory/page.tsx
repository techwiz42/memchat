"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isLoggedIn } from "@/lib/auth";
import { apiFetch } from "@/lib/api";

interface Memory {
  id: string;
  content: string;
  created_at: string;
}

interface MemoryListResponse {
  items: Memory[];
  total: number;
}

export default function MemoryPage() {
  const router = useRouter();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [newContent, setNewContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Memory[] | null>(null);
  const [searching, setSearching] = useState(false);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    loadMemories(1);
  }, [router]);

  async function loadMemories(p: number) {
    setLoading(true);
    try {
      const data = await apiFetch<MemoryListResponse>(`/memory?page=${p}&per_page=20`);
      if (p === 1) {
        setMemories(data.items);
      } else {
        setMemories((prev) => [...prev, ...data.items]);
      }
      setTotal(data.total);
      setPage(p);
    } catch (err) {
      console.error("Failed to load memories:", err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    searchTimerRef.current = setTimeout(async () => {
      try {
        const results = await apiFetch<Memory[]>(
          `/memory/search?q=${encodeURIComponent(q)}`
        );
        setSearchResults(results);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    };
  }, [searchQuery]);

  async function handleAdd() {
    if (!newContent.trim() || saving) return;
    setSaving(true);
    try {
      const mem = await apiFetch<Memory>("/memory", {
        method: "POST",
        body: JSON.stringify({ content: newContent.trim() }),
      });
      setMemories((prev) => [mem, ...prev]);
      setTotal((t) => t + 1);
      setNewContent("");
    } catch (err) {
      console.error("Failed to add memory:", err);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await apiFetch(`/memory/${id}`, { method: "DELETE" });
      setMemories((prev) => prev.filter((m) => m.id !== id));
      setTotal((t) => t - 1);
      if (searchResults) {
        setSearchResults((prev) => prev?.filter((m) => m.id !== id) ?? null);
      }
    } catch (err) {
      console.error("Failed to delete memory:", err);
    }
  }

  const displayList = searchResults !== null ? searchResults : memories;
  const hasMore = searchResults === null && memories.length < total;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-semibold">Memories</h1>
        <Link
          href="/chat"
          className="text-sm text-blue-600 hover:text-blue-800 font-medium"
        >
          Back to Chat
        </Link>
      </header>

      <div className="max-w-2xl mx-auto py-6 px-4 space-y-6">
        {/* Search */}
        <div className="relative">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Semantic search across memories..."
            className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* Add memory */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h2 className="text-sm font-medium text-gray-700 mb-2">Add a memory</h2>
          <textarea
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="Type something you want the AI to remember..."
            rows={3}
            maxLength={5000}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-vertical"
          />
          <div className="flex justify-between items-center mt-2">
            <span className="text-xs text-gray-400">{newContent.length}/5000</span>
            <button
              onClick={handleAdd}
              disabled={saving || !newContent.trim()}
              className="bg-blue-600 text-white rounded-lg px-4 py-1.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>

        {/* Memory list */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-gray-700">
              {searchResults !== null
                ? `${searchResults.length} search result${searchResults.length !== 1 ? "s" : ""}`
                : `${total} memor${total !== 1 ? "ies" : "y"}`}
            </h2>
          </div>

          {loading && memories.length === 0 ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin w-6 h-6 border-3 border-blue-600 border-t-transparent rounded-full" />
            </div>
          ) : searching ? (
            <p className="text-center text-sm text-gray-400 py-8">Searching...</p>
          ) : displayList.length === 0 ? (
            <p className="text-center text-sm text-gray-400 py-8">
              {searchResults !== null ? "No matching memories" : "No memories yet"}
            </p>
          ) : (
            <ul className="space-y-2">
              {displayList.map((mem) => (
                <li
                  key={mem.id}
                  className="bg-white rounded-lg border border-gray-200 p-3 group"
                >
                  <div className="flex justify-between items-start gap-3">
                    <p className="text-sm text-gray-800 whitespace-pre-wrap flex-1 line-clamp-4">
                      {mem.content}
                    </p>
                    <button
                      onClick={() => handleDelete(mem.id)}
                      className="shrink-0 p-1 text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
                      title="Delete memory"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                  <p className="text-xs text-gray-400 mt-1.5">
                    {new Date(mem.created_at).toLocaleDateString(undefined, {
                      year: "numeric", month: "short", day: "numeric",
                      hour: "2-digit", minute: "2-digit",
                    })}
                  </p>
                </li>
              ))}
            </ul>
          )}

          {hasMore && (
            <button
              onClick={() => loadMemories(page + 1)}
              disabled={loading}
              className="w-full mt-4 py-2 text-sm text-blue-600 hover:text-blue-800 font-medium disabled:opacity-50"
            >
              {loading ? "Loading..." : "Load more"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
