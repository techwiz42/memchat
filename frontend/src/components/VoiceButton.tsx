"use client";

import { VoiceStatus } from "@/hooks/useVoiceSession";

interface Props {
  isActive: boolean;
  status: VoiceStatus;
  onStart: () => void;
  onEnd: () => void;
}

export default function VoiceButton({ isActive, status, onStart, onEnd }: Props) {
  const isConnecting = status === "connecting" || status === "disconnecting";

  const handleClick = async () => {
    if (isActive) {
      onEnd();
    } else {
      onStart();
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={isConnecting}
      className={`relative w-12 h-12 rounded-full flex items-center justify-center transition-all ${
        isActive
          ? "bg-red-500 hover:bg-red-600 text-white"
          : "bg-gray-100 hover:bg-gray-200 text-gray-600"
      } ${isConnecting ? "opacity-50 cursor-not-allowed" : ""}`}
      title={isActive ? "End voice session" : "Start voice session"}
    >
      {isConnecting ? (
        <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" />
        </svg>
      )}

      {isActive && !isConnecting && (
        <span className="absolute -top-0.5 -right-0.5 w-3 h-3 bg-red-400 rounded-full animate-pulse" />
      )}
    </button>
  );
}
