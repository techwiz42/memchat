"use client";

interface Transcript {
  speaker: "user" | "agent";
  text: string;
  isFinal: boolean;
}

interface Props {
  transcripts: Transcript[];
}

export default function TranscriptPanel({ transcripts }: Props) {
  if (transcripts.length === 0) return null;

  return (
    <div className="bg-gray-900/90 backdrop-blur text-white rounded-xl p-4 max-h-48 overflow-y-auto">
      <div className="text-xs text-gray-400 font-medium mb-2 uppercase tracking-wide">
        Live Transcript
      </div>
      <div className="space-y-1.5">
        {transcripts.map((t, i) => (
          <div key={i} className={`text-sm ${t.isFinal ? "opacity-100" : "opacity-60"}`}>
            <span className={`font-medium ${t.speaker === "user" ? "text-blue-300" : "text-green-300"}`}>
              {t.speaker === "user" ? "You" : "Assistant"}:
            </span>{" "}
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}
