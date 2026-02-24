"use client";

import { useCallback } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import { ChatMessage } from "@/hooks/useChat";
import { getAccessToken } from "@/lib/auth";

interface Props {
  message: ChatMessage;
}

const DOC_PATTERN = /\[Uploaded document: (.+?)\]/;
const DOWNLOAD_PATH_PREFIX = "/api/documents/download/";

/**
 * Authenticated file download: fetch with Bearer token, then trigger
 * a browser download from the resulting blob.
 */
async function authenticatedDownload(href: string) {
  const token = getAccessToken();
  const res = await fetch(href, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error(`Download failed: ${res.status}`);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch ? filenameMatch[1] : "download";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const docMatch = message.content.match(DOC_PATTERN);

  // For user messages with a document upload, split out the filename
  const docFilename = docMatch ? docMatch[1] : null;
  const textContent = docMatch
    ? message.content.replace(DOC_PATTERN, "").trim()
    : message.content;

  // Custom link renderer: intercept download links to use authenticated fetch
  const handleDownloadClick = useCallback(
    (e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
      e.preventDefault();
      authenticatedDownload(href).catch((err) => {
        console.error("Download error:", err);
        alert("Download failed. The file may have expired — please ask the agent to generate it again.");
      });
    },
    []
  );

  const markdownComponents: Components = {
    a: ({ href, children, ...props }) => {
      // Normalize href: strip scheme prefixes the LLM may hallucinate (e.g. "sandbox:")
      let cleanHref = href || "";
      const dlIdx = cleanHref.indexOf(DOWNLOAD_PATH_PREFIX);
      const isDownloadLink = dlIdx !== -1;
      if (isDownloadLink) {
        cleanHref = cleanHref.slice(dlIdx); // keep only from /api/documents/download/...
        return (
          <a
            href={cleanHref}
            onClick={(e) => handleDownloadClick(e, cleanHref)}
            className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 underline font-medium cursor-pointer"
            {...props}
          >
            <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            {children}
          </a>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    },
  };

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-2.5 ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-gray-100 text-gray-900"
        }`}
      >
        {docFilename && (
          <div
            className={`flex items-center gap-1.5 text-xs mb-1.5 ${
              isUser ? "text-blue-200" : "text-gray-500"
            }`}
          >
            <svg
              className="w-3.5 h-3.5 shrink-0"
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
            <span className="truncate">{docFilename}</span>
          </div>
        )}
        {textContent && (
          isUser ? (
            <p className="whitespace-pre-wrap text-sm">{textContent}</p>
          ) : (
            <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-pre:my-2 prose-code:text-inherit prose-code:before:content-none prose-code:after:content-none">
              <ReactMarkdown components={markdownComponents}>{textContent}</ReactMarkdown>
            </div>
          )
        )}
        <div
          className={`flex items-center gap-2 mt-1 text-xs ${
            isUser ? "text-blue-200" : "text-gray-400"
          }`}
        >
          {message.source === "voice" && (
            <span className="inline-flex items-center gap-0.5">
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" />
              </svg>
              voice
            </span>
          )}
          {message.source === "vision" && (
            <span className="inline-flex items-center gap-0.5">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              vision
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
