"use client";

import { VoiceStatus as VoiceStatusType } from "@/hooks/useVoiceSession";

interface Props {
  status: VoiceStatusType;
}

const STATUS_CONFIG: Record<
  VoiceStatusType,
  { label: string; color: string; animate: boolean }
> = {
  idle: { label: "", color: "", animate: false },
  connecting: { label: "Connecting...", color: "text-yellow-600", animate: true },
  listening: { label: "Listening", color: "text-green-600", animate: true },
  thinking: { label: "Thinking...", color: "text-blue-600", animate: true },
  speaking: { label: "Speaking", color: "text-purple-600", animate: true },
  disconnecting: { label: "Disconnecting...", color: "text-gray-500", animate: true },
};

export default function VoiceStatus({ status }: Props) {
  if (status === "idle") return null;

  const config = STATUS_CONFIG[status];

  return (
    <div className={`flex items-center gap-2 text-sm font-medium ${config.color}`}>
      {config.animate && (
        <span className="flex gap-0.5">
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse [animation-delay:0.15s]" />
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse [animation-delay:0.3s]" />
        </span>
      )}
      {config.label}
    </div>
  );
}
