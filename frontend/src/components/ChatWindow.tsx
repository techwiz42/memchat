"use client";

import { useRef, useEffect, useState, FormEvent, DragEvent } from "react";
import { ChatMessage, UploadResponse } from "@/hooks/useChat";
import MessageBubble from "./MessageBubble";

const ACCEPTED_EXTENSIONS =
  ".txt,.md,.pdf,.docx,.xlsx,.csv,.fdx,.jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff";

interface Props {
  messages: ChatMessage[];
  loading: boolean;
  historyTokens?: number | null;
  progressLines?: string[];
  onSend: (text: string) => void;
  onSendWithFile: (text: string, file: File) => Promise<UploadResponse | null>;
  onFileProcessed?: (file: File, result: UploadResponse) => void;
  onEditMessage?: (id: string, content: string) => void;
  onRegenerateMessage?: (id: string) => void;
}

export default function ChatWindow({
  messages,
  loading,
  historyTokens,
  progressLines = [],
  onSend,
  onSendWithFile,
  onFileProcessed,
  onEditMessage,
  onRegenerateMessage,
}: Props) {
  const [input, setInput] = useState("");
  const [dragging, setDragging] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (loading || !text) return;
    onSend(text);
    setInput("");
  };

  const handleFileSelect = (files: FileList | null) => {
    if (!files || files.length === 0 || loading) return;
    const file = files[0];
    onSendWithFile("", file).then((result) => {
      if (result && onFileProcessed) onFileProcessed(file, result);
    });
  };

  const handleDragEnter = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current++;
    if (e.dataTransfer.types.includes("Files")) {
      setDragging(true);
    }
  };

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current === 0) {
      setDragging(false);
    }
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setDragging(false);

    const files = e.dataTransfer.files;
    if (files.length > 0 && !loading) {
      const file = files[0];
      onSendWithFile("", file).then((result) => {
        if (result && onFileProcessed) onFileProcessed(file, result);
      });
    }
  };

  return (
    <div
      className="flex flex-col h-full relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {dragging && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-blue-50/80 border-2 border-dashed border-blue-400 rounded-lg pointer-events-none">
          <div className="text-center">
            <svg
              className="w-12 h-12 mx-auto text-blue-500 mb-2"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
              />
            </svg>
            <p className="text-blue-600 font-medium">Drop file to upload</p>
            <p className="text-blue-400 text-sm mt-1">
              PDF, DOCX, TXT, MD, XLSX, CSV, JPG, PNG, GIF, WEBP
            </p>
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-400">
            <p>Start a conversation...</p>
          </div>
        )}
        {messages.map((msg) =>
          msg.content ? (
            <MessageBubble
              key={msg.id}
              message={msg}
              onEdit={onEditMessage}
              onRegenerate={onRegenerateMessage}
            />
          ) : null,
        )}
        {loading && (
          <div className="flex justify-start mb-3">
            <div className="bg-gray-100 rounded-2xl px-4 py-2.5">
              {progressLines.length > 0 && (
                <div className="text-xs text-gray-500 mb-1.5 space-y-0.5">
                  {progressLines.map((line, i) => (
                    <div key={i}>{line}</div>
                  ))}
                </div>
              )}
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.1s]" />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]" />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <form onSubmit={handleSubmit} className="border-t border-gray-200 p-4">
        {historyTokens != null && (
          <div className="text-xs text-gray-400 mb-1.5 text-right">
            {historyTokens.toLocaleString()} history tokens
          </div>
        )}
        <div className="flex gap-2">
          {/* File attach button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={loading}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors p-2"
            title=""
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
              />
            </svg>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            onChange={(e) => handleFileSelect(e.target.files)}
            className="hidden"
          />

          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (!loading && input.trim()) {
                  onSend(input.trim());
                  setInput("");
                }
              }
            }}
            placeholder="Type a message..."
            rows={3}
            className="flex-1 rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="bg-blue-600 text-white rounded-xl px-5 py-2.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
