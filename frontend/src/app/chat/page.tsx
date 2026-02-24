"use client";

import { useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isLoggedIn } from "@/lib/auth";
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
  const router = useRouter();
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
          <span className="text-sm text-gray-500">{user?.email}</span>
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
            onSend={sendMessage}
            onSendWithFile={sendMessageWithFile}
            onFileProcessed={handleFileProcessed}
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
