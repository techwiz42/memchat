"use client";

import { VideoStatus } from "@/hooks/useVideoStream";

interface Props {
  isActive: boolean;
  status: VideoStatus;
  onStart: () => void;
  onStop: () => void;
}

export default function CameraButton({ isActive, status, onStart, onStop }: Props) {
  const isTransitioning = status === "connecting" || status === "disconnecting";

  const handleClick = () => {
    if (isActive) {
      onStop();
    } else {
      onStart();
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={isTransitioning}
      className={`relative w-12 h-12 rounded-full flex items-center justify-center transition-all ${
        isActive
          ? "bg-green-500 hover:bg-green-600 text-white"
          : "bg-gray-100 hover:bg-gray-200 text-gray-600"
      } ${isTransitioning ? "opacity-50 cursor-not-allowed" : ""}`}
      title={isActive ? "Stop camera" : "Start camera"}
    >
      {isTransitioning ? (
        <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
          />
        </svg>
      )}

      {isActive && !isTransitioning && (
        <span className="absolute -top-0.5 -right-0.5 w-3 h-3 bg-green-400 rounded-full animate-pulse" />
      )}
    </button>
  );
}
