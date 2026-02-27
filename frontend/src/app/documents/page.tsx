"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isLoggedIn } from "@/lib/auth";
import { apiFetch } from "@/lib/api";

interface DocumentItem {
  id: string;
  filename: string;
  conversation_id: string;
  conversation_title: string;
  created_at: string;
  size: number;
}

interface DocumentListResponse {
  items: DocumentItem[];
  total: number;
}

interface DocumentDetail {
  id: string;
  filename: string;
  content: string;
  sections_json: unknown[] | null;
  created_at: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const router = useRouter();
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedContent, setExpandedContent] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    loadDocuments(1);
  }, [router]);

  async function loadDocuments(p: number) {
    setLoading(true);
    try {
      const data = await apiFetch<DocumentListResponse>(
        `/documents/library?page=${p}&per_page=20`
      );
      if (p === 1) {
        setDocuments(data.items);
      } else {
        setDocuments((prev) => [...prev, ...data.items]);
      }
      setTotal(data.total);
      setPage(p);
    } catch (err) {
      console.error("Failed to load documents:", err);
    } finally {
      setLoading(false);
    }
  }

  async function handleExpand(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      setExpandedContent(null);
      return;
    }
    setExpandedId(id);
    setExpandedContent(null);
    setLoadingContent(true);
    try {
      const detail = await apiFetch<DocumentDetail>(`/documents/library/${id}`);
      setExpandedContent(detail.content);
    } catch (err) {
      console.error("Failed to load document:", err);
      setExpandedContent("Failed to load document content.");
    } finally {
      setLoadingContent(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await apiFetch(`/documents/library/${id}`, { method: "DELETE" });
      setDocuments((prev) => prev.filter((d) => d.id !== id));
      setTotal((t) => t - 1);
      if (expandedId === id) {
        setExpandedId(null);
        setExpandedContent(null);
      }
    } catch (err) {
      console.error("Failed to delete document:", err);
    } finally {
      setConfirmDeleteId(null);
    }
  }

  const hasMore = documents.length < total;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-semibold">Documents</h1>
        <Link
          href="/chat"
          className="text-sm text-blue-600 hover:text-blue-800 font-medium"
        >
          Back to Chat
        </Link>
      </header>

      <div className="max-w-2xl mx-auto py-6 px-4">
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm text-gray-500">
            {total} document{total !== 1 ? "s" : ""}
          </p>
        </div>

        {loading && documents.length === 0 ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin w-6 h-6 border-3 border-blue-600 border-t-transparent rounded-full" />
          </div>
        ) : documents.length === 0 ? (
          <p className="text-center text-sm text-gray-400 py-8">
            No documents uploaded yet. Upload a file in chat to get started.
          </p>
        ) : (
          <ul className="space-y-2">
            {documents.map((doc) => (
              <li
                key={doc.id}
                className="bg-white rounded-lg border border-gray-200 overflow-hidden"
              >
                <div className="p-3 flex items-center gap-3">
                  {/* File icon */}
                  <svg
                    className="w-5 h-5 text-gray-400 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>

                  {/* Info */}
                  <button
                    onClick={() => handleExpand(doc.id)}
                    className="flex-1 text-left min-w-0"
                  >
                    <div className="text-sm font-medium text-gray-800 truncate">
                      {doc.filename}
                    </div>
                    <div className="text-xs text-gray-400 flex gap-2 mt-0.5">
                      <span>{formatSize(doc.size)}</span>
                      <span>
                        {new Date(doc.created_at).toLocaleDateString(undefined, {
                          year: "numeric", month: "short", day: "numeric",
                        })}
                      </span>
                    </div>
                    <div className="text-xs text-blue-500 truncate mt-0.5">
                      {doc.conversation_title}
                    </div>
                  </button>

                  {/* Actions */}
                  <div className="flex items-center gap-1 shrink-0">
                    <Link
                      href={`/chat?c=${doc.conversation_id}`}
                      className="p-1.5 text-gray-400 hover:text-blue-500 transition-colors"
                      title="Open conversation"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                      </svg>
                    </Link>
                    {confirmDeleteId === doc.id ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleDelete(doc.id)}
                          className="text-xs px-1.5 py-0.5 bg-red-500 text-white rounded hover:bg-red-600"
                        >
                          Yes
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="text-xs px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded hover:bg-gray-300"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(doc.id)}
                        className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                        title="Delete document"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>

                {/* Expanded content */}
                {expandedId === doc.id && (
                  <div className="border-t border-gray-100 p-3 bg-gray-50">
                    {loadingContent ? (
                      <div className="flex justify-center py-4">
                        <div className="animate-spin w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full" />
                      </div>
                    ) : (
                      <pre className="text-xs text-gray-700 whitespace-pre-wrap max-h-80 overflow-y-auto font-mono">
                        {expandedContent}
                      </pre>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}

        {hasMore && (
          <button
            onClick={() => loadDocuments(page + 1)}
            disabled={loading}
            className="w-full mt-4 py-2 text-sm text-blue-600 hover:text-blue-800 font-medium disabled:opacity-50"
          >
            {loading ? "Loading..." : "Load more"}
          </button>
        )}
      </div>
    </div>
  );
}
