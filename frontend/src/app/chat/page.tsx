"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isLoggedIn } from "@/lib/auth";
import { useAuth } from "@/hooks/useAuth";
import { useChat } from "@/hooks/useChat";
import { useVoiceSession } from "@/hooks/useVoiceSession";
import ChatWindow from "@/components/ChatWindow";
import VoiceButton from "@/components/VoiceButton";
import VoiceStatus from "@/components/VoiceStatus";
import TranscriptPanel from "@/components/TranscriptPanel";

export default function ChatPage() {
  const router = useRouter();
  const { user, loading: authLoading, logout } = useAuth();
  const { messages, loading: chatLoading, sendMessage, sendMessageWithFile, appendVoiceTranscript } = useChat();
  const { status, transcripts, isActive, startSession, endSession } = useVoiceSession();

  useEffect(() => {
    if (!authLoading && !isLoggedIn()) {
      router.replace("/login");
    }
  }, [authLoading, router]);

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

      {/* Chat area */}
      <main className="flex-1 overflow-hidden relative">
        <ChatWindow
          messages={messages}
          loading={chatLoading}
          onSend={sendMessage}
          onSendWithFile={sendMessageWithFile}
        />

        {/* Voice transcript overlay */}
        {isActive && (
          <div className="absolute bottom-20 left-4 right-4">
            <TranscriptPanel transcripts={transcripts} />
          </div>
        )}
      </main>
    </div>
  );
}
