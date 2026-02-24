"use client";

import { useState, useCallback, useRef } from "react";
import { getAccessToken } from "@/lib/auth";

export type VideoStatus = "idle" | "connecting" | "streaming" | "disconnecting";

export interface DetectionResult {
  objects: Record<string, number>;
  frame: number;
}

interface UseVideoStreamOptions {
  onAnalysis?: (content: string, trigger: string) => void;
}

export function useVideoStream({ onAnalysis }: UseVideoStreamOptions = {}) {
  const [status, setStatus] = useState<VideoStatus>("idle");
  const [detections, setDetections] = useState<Record<string, number>>({});
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onAnalysisRef = useRef(onAnalysis);
  onAnalysisRef.current = onAnalysis;

  const isActive = status === "streaming";

  const startStream = useCallback(async () => {
    if (wsRef.current) return;

    setStatus("connecting");

    try {
      // Get camera access
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "user" },
        audio: false,
      });
      streamRef.current = stream;
      setMediaStream(stream);

      // Create an offscreen video element for canvas drawing
      const offscreenVideo = document.createElement("video");
      offscreenVideo.srcObject = stream;
      offscreenVideo.muted = true;
      offscreenVideo.playsInline = true;
      await offscreenVideo.play();

      // Connect WebSocket with JWT auth
      const token = getAccessToken();
      if (!token) {
        throw new Error("Not authenticated");
      }

      const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${wsProtocol}//${window.location.host}/api/vision/stream?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        setStatus("streaming");

        // Create offscreen canvas for frame capture
        const canvas = document.createElement("canvas");
        canvas.width = 640;
        canvas.height = 480;

        // Send frames at 2 FPS
        intervalRef.current = setInterval(() => {
          if (ws.readyState !== WebSocket.OPEN) return;

          const ctx = canvas.getContext("2d");
          if (!ctx) return;

          ctx.drawImage(offscreenVideo, 0, 0, 640, 480);
          canvas.toBlob(
            (blob) => {
              if (blob && ws.readyState === WebSocket.OPEN) {
                blob.arrayBuffer().then((buf) => ws.send(buf));
              }
            },
            "image/jpeg",
            0.7
          );
        }, 500); // 2 FPS
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "detection") {
            setDetections(msg.objects || {});
          } else if (msg.type === "analysis") {
            onAnalysisRef.current?.(msg.content, msg.trigger);
          } else if (msg.type === "error") {
            console.error("Vision stream error:", msg.message);
          }
        } catch {
          // Ignore non-JSON messages
        }
      };

      ws.onclose = () => {
        cleanup();
        setStatus("idle");
      };

      ws.onerror = (err) => {
        console.error("Vision WebSocket error:", err);
        cleanup();
        setStatus("idle");
      };
    } catch (e) {
      console.error("Failed to start video stream:", e);
      cleanup();
      setStatus("idle");
      throw e;
    }
  }, []);

  const cleanup = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "stop" }));
      }
      wsRef.current.close();
      wsRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setMediaStream(null);
    setDetections({});
  }, []);

  const stopStream = useCallback(() => {
    setStatus("disconnecting");
    cleanup();
    setStatus("idle");
  }, [cleanup]);

  return {
    status,
    isActive,
    detections,
    mediaStream,
    startStream,
    stopStream,
  };
}
