"use client";

import { Suspense, useState, useEffect, useRef, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { isLoggedIn, getAccessToken, refreshAccessToken } from "@/lib/auth";
import { useAuth } from "@/hooks/useAuth";
import { useChat, UploadResponse } from "@/hooks/useChat";
import { useConversations } from "@/hooks/useConversations";
import { useVoiceSession } from "@/hooks/useVoiceSession";
import { useVideoStream } from "@/hooks/useVideoStream";
import ChatWindow from "@/components/ChatWindow";
import ChatSidebar from "@/components/ChatSidebar";
import VoiceButton from "@/components/VoiceButton";
import VoiceStatus from "@/components/VoiceStatus";
import TranscriptPanel from "@/components/TranscriptPanel";
import CameraButton from "@/components/CameraButton";
import VideoPreview from "@/components/VideoPreview";

export default function ChatPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-screen">
        <div className="animate-spin w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full" />
      </div>
    }>
      <ChatPageInner />
    </Suspense>
  );
}

function ChatPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading: authLoading, logout } = useAuth();
  const {
    messages,
    loading: chatLoading,
    conversationId,
    sendMessage,
    sendMessageWithFile,
    appendVoiceTranscript,
    appendVisionAnalysis,
    newConversation,
    selectConversation,
    historyTokens,
    progressLines,
    editMessage,
    regenerateAfter,
  } = useChat();
  const { conversations, loadConversations, deleteConversation } = useConversations();
  const { status, transcripts, isActive, startSession, endSession, sendText } = useVoiceSession();

  // Refs for voice state so the video onAnalysis callback always reads fresh values
  const isVoiceActiveRef = useRef(isActive);
  isVoiceActiveRef.current = isActive;
  const sendTextRef = useRef(sendText);
  sendTextRef.current = sendText;

  const {
    status: cameraStatus,
    isActive: isCameraActive,
    detections,
    mediaStream,
    startStream,
    stopStream,
  } = useVideoStream({
    onAnalysis: (content, trigger) => {
      appendVisionAnalysis(content);
      if (isVoiceActiveRef.current) {
        sendTextRef.current(
          `[Vision update — ${trigger}] Here is what the camera sees: ${content}`
        );
      }
    },
  });
  const voiceFileRef = useRef<HTMLInputElement>(null);

  // Load conversations on mount
  useEffect(() => {
    if (!authLoading && isLoggedIn()) {
      loadConversations();
    }
  }, [authLoading, loadConversations]);

  // Handle ?c=conversationId query param (e.g. from document library)
  useEffect(() => {
    const cParam = searchParams.get("c");
    if (cParam && !authLoading && isLoggedIn()) {
      selectConversation(cParam);
    }
  }, [searchParams, authLoading, selectConversation]);

  // Refresh sidebar whenever conversationId changes (new conversation created)
  useEffect(() => {
    if (conversationId) {
      loadConversations();
    }
  }, [conversationId, loadConversations]);

  const handleVoiceFileSelect = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];
    if (voiceFileRef.current) voiceFileRef.current.value = "";
    const result = await sendMessageWithFile("", file);
    if (result && isActive) {
      sendText(
        `The user just uploaded a file called "${file.name}". ` +
        `It has been analyzed and added to the knowledge base. ` +
        `Here is the extracted content:\n\n${result.extracted_text}\n\n` +
        `Acknowledge the upload and briefly describe what you see in it.`
      );
    }
  };

  useEffect(() => {
    if (!authLoading && !isLoggedIn()) {
      router.replace("/login");
    }
  }, [authLoading, router]);

  const handleFileProcessed = useCallback((file: File, result: UploadResponse) => {
    if (isActive) {
      sendText(
        `The user just uploaded a file called "${file.name}". ` +
        `It has been analyzed and added to the knowledge base. ` +
        `Here is the extracted content:\n\n${result.extracted_text}\n\n` +
        `Acknowledge the upload and briefly describe what you see in it.`
      );
    }
  }, [isActive, sendText]);

  const handleStartCamera = useCallback(async () => {
    try {
      await startStream();
    } catch (e) {
      console.error("Camera start failed:", e);
    }
  }, [startStream]);

  const handleStopCamera = useCallback(() => {
    stopStream();
  }, [stopStream]);

  const handleStartVoice = async () => {
    try {
      await startSession();
    } catch (e) {
      console.error("Voice start failed:", e);
    }
  };

  const handleEndVoice = async () => {
    const transcript = await endSession();
    if (transcript) {
      appendVoiceTranscript(transcript);
    }
  };

  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  // Close export menu on click outside
  useEffect(() => {
    if (!showExportMenu) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showExportMenu]);

  const handleExport = useCallback(async (format: string) => {
    if (!conversationId) return;
    setShowExportMenu(false);
    const url = `/api/conversations/${conversationId}/export?format=${format}`;
    let token = getAccessToken();
    let res = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (res.status === 401) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        res = await fetch(url, { headers: { Authorization: `Bearer ${newToken}` } });
      }
    }
    if (!res.ok) return;
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const fallback = `conversation.${format}`;
    const filename = match ? match[1] : fallback;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  }, [conversationId]);

  const handleNewChat = useCallback(() => {
    newConversation();
  }, [newConversation]);

  const handleSelectConversation = useCallback((id: string) => {
    selectConversation(id);
  }, [selectConversation]);

  const handleDeleteConversation = useCallback(async (id: string) => {
    await deleteConversation(id);
    // If we deleted the active conversation, clear the canvas
    if (id === conversationId) {
      newConversation();
    }
  }, [deleteConversation, conversationId, newConversation]);

  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="animate-spin w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-semibold">Memchat</h1>
        <div className="flex items-center gap-3">
          <VoiceStatus status={status} />
          <VoiceButton
            isActive={isActive}
            status={status}
            onStart={handleStartVoice}
            onEnd={handleEndVoice}
          />
          <CameraButton
            isActive={isCameraActive}
            status={cameraStatus}
            onStart={handleStartCamera}
            onStop={handleStopCamera}
          />
          {conversationId && (
            <div className="relative" ref={exportMenuRef}>
              <button
                onClick={() => setShowExportMenu((v) => !v)}
                className="text-gray-400 hover:text-gray-600 transition-colors"
                title="Export conversation"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                  <path d="M10.75 2.75a.75.75 0 0 0-1.5 0v8.614L6.295 8.235a.75.75 0 1 0-1.09 1.03l4.25 4.5a.75.75 0 0 0 1.09 0l4.25-4.5a.75.75 0 0 0-1.09-1.03l-2.955 3.129V2.75Z" />
                  <path d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z" />
                </svg>
              </button>
              {showExportMenu && (
                <div className="absolute right-0 mt-2 w-44 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50">
                  <button
                    onClick={() => handleExport("md")}
                    className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                  >
                    Markdown (.md)
                  </button>
                  <button
                    onClick={() => handleExport("docx")}
                    className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                  >
                    Word (.docx)
                  </button>
                  <button
                    onClick={() => handleExport("pdf")}
                    className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                  >
                    PDF (.pdf)
                  </button>
                </div>
              )}
            </div>
          )}
          <span className="text-sm text-gray-500">{user?.email}</span>
          <Link
            href="/memory"
            className="text-gray-400 hover:text-gray-600 transition-colors"
            title="Memories"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
              <path d="M10 .5a9.5 9.5 0 1 0 5.598 17.177C14.53 15.749 12.412 14.5 10 14.5c-2.133 0-4.04.975-5.293 2.5A9.456 9.456 0 0 1 .5 10a9.5 9.5 0 0 1 9.5-9.5Zm0 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z" />
            </svg>
          </Link>
          <Link
            href="/documents"
            className="text-gray-400 hover:text-gray-600 transition-colors"
            title="Documents"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
              <path d="M3 3.5A1.5 1.5 0 0 1 4.5 2h6.879a1.5 1.5 0 0 1 1.06.44l4.122 4.12A1.5 1.5 0 0 1 17 7.622V16.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 16.5v-13Zm10.5 5.5a1 1 0 0 0-1-1H7.5a1 1 0 0 0 0 2h5a1 1 0 0 0 1-1Zm0 3a1 1 0 0 0-1-1H7.5a1 1 0 0 0 0 2h5a1 1 0 0 0 1-1Zm-7-3.75a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z" />
            </svg>
          </Link>
          {user?.email === "pete@cyberiad.ai" && (
            <Link
              href="/admin"
              className="text-gray-400 hover:text-gray-600 transition-colors"
              title="Admin"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                <path fillRule="evenodd" d="M2 4.25A2.25 2.25 0 0 1 4.25 2h11.5A2.25 2.25 0 0 1 18 4.25v8.5A2.25 2.25 0 0 1 15.75 15h-3.105a3.501 3.501 0 0 0 1.1 1.677A.75.75 0 0 1 13.26 18H6.74a.75.75 0 0 1-.484-1.323A3.501 3.501 0 0 0 7.355 15H4.25A2.25 2.25 0 0 1 2 12.75v-8.5Zm1.5 0a.75.75 0 0 1 .75-.75h11.5a.75.75 0 0 1 .75.75v7.5a.75.75 0 0 1-.75.75H4.25a.75.75 0 0 1-.75-.75v-7.5Z" clipRule="evenodd" />
              </svg>
            </Link>
          )}
          <Link
            href="/settings"
            className="text-gray-400 hover:text-gray-600 transition-colors"
            title="Settings"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
              <path fillRule="evenodd" d="M7.84 1.804A1 1 0 0 1 8.82 1h2.36a1 1 0 0 1 .98.804l.331 1.652a6.993 6.993 0 0 1 1.929 1.115l1.598-.54a1 1 0 0 1 1.186.447l1.18 2.044a1 1 0 0 1-.205 1.251l-1.267 1.113a7.047 7.047 0 0 1 0 2.228l1.267 1.113a1 1 0 0 1 .206 1.25l-1.18 2.045a1 1 0 0 1-1.187.447l-1.598-.54a6.993 6.993 0 0 1-1.929 1.115l-.33 1.652a1 1 0 0 1-.98.804H8.82a1 1 0 0 1-.98-.804l-.331-1.652a6.993 6.993 0 0 1-1.929-1.115l-1.598.54a1 1 0 0 1-1.186-.447l-1.18-2.044a1 1 0 0 1 .205-1.251l1.267-1.114a7.05 7.05 0 0 1 0-2.227L1.821 7.773a1 1 0 0 1-.206-1.25l1.18-2.045a1 1 0 0 1 1.187-.447l1.598.54A6.992 6.992 0 0 1 7.51 3.456l.33-1.652ZM10 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" clipRule="evenodd" />
            </svg>
          </Link>
          <button
            onClick={() => {
              logout();
              router.push("/login");
            }}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* Main area: sidebar + chat */}
      <div className="flex flex-1 overflow-hidden">
        <ChatSidebar
          conversations={conversations}
          activeId={conversationId}
          onNewChat={handleNewChat}
          onSelect={handleSelectConversation}
          onDelete={handleDeleteConversation}
        />

        {/* Chat area */}
        <main className="flex-1 overflow-hidden relative">
          {mediaStream && cameraStatus !== "idle" && (
            <VideoPreview mediaStream={mediaStream} detections={detections} />
          )}
          <ChatWindow
            messages={messages}
            loading={chatLoading}
            historyTokens={historyTokens}
            progressLines={progressLines}
            onSend={sendMessage}
            onSendWithFile={sendMessageWithFile}
            onFileProcessed={handleFileProcessed}
            onEditMessage={editMessage}
            onRegenerateMessage={regenerateAfter}
          />

          {/* Voice transcript overlay */}
          {isActive && (
            <div className="absolute bottom-20 left-4 right-4">
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <TranscriptPanel transcripts={transcripts} />
                </div>
                <button
                  type="button"
                  onClick={() => voiceFileRef.current?.click()}
                  disabled={chatLoading}
                  className="shrink-0 w-12 h-12 rounded-full bg-white shadow-lg border border-gray-200 flex items-center justify-center text-gray-500 hover:text-blue-600 hover:border-blue-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  title="Upload image or document"
                >
                  {chatLoading ? (
                    <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                    </svg>
                  )}
                </button>
                <input
                  ref={voiceFileRef}
                  type="file"
                  accept=".txt,.md,.pdf,.docx,.xlsx,.csv,.fdx,.jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff"
                  onChange={(e) => handleVoiceFileSelect(e.target.files)}
                  className="hidden"
                />
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
