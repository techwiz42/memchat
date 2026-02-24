"use client";

import { useEffect, useRef } from "react";

interface Props {
  mediaStream: MediaStream;
  detections: Record<string, number>;
}

export default function VideoPreview({ mediaStream, detections }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = mediaStream;
    }
  }, [mediaStream]);

  const detectionEntries = Object.entries(detections);
  const detectionText = detectionEntries.length > 0
    ? detectionEntries.map(([cls, count]) => `${cls}: ${count}`).join(", ")
    : "scanning...";

  return (
    <div className="absolute top-4 right-4 z-10 w-48 rounded-lg overflow-hidden shadow-lg border border-gray-200 bg-black">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="w-full h-36 object-cover"
      />
      <div className="bg-black/70 text-white text-xs px-2 py-1 truncate">
        {detectionText}
      </div>
    </div>
  );
}
