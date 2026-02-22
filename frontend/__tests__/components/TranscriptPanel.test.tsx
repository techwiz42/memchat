import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import TranscriptPanel from "@/components/TranscriptPanel";

describe("TranscriptPanel", () => {
  it("returns null when no transcripts", () => {
    const { container } = render(<TranscriptPanel transcripts={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders header", () => {
    render(
      <TranscriptPanel
        transcripts={[{ speaker: "user", text: "Hello", isFinal: true }]}
      />
    );
    expect(screen.getByText("Live Transcript")).toBeInTheDocument();
  });

  it("shows user speaker label as You", () => {
    render(
      <TranscriptPanel
        transcripts={[{ speaker: "user", text: "Hello", isFinal: true }]}
      />
    );
    expect(screen.getByText("You:")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("shows agent speaker label as Assistant", () => {
    render(
      <TranscriptPanel
        transcripts={[{ speaker: "agent", text: "Hi there", isFinal: true }]}
      />
    );
    expect(screen.getByText("Assistant:")).toBeInTheDocument();
    expect(screen.getByText("Hi there")).toBeInTheDocument();
  });

  it("renders multiple transcripts", () => {
    render(
      <TranscriptPanel
        transcripts={[
          { speaker: "user", text: "First", isFinal: true },
          { speaker: "agent", text: "Second", isFinal: true },
          { speaker: "user", text: "Third", isFinal: false },
        ]}
      />
    );
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
    expect(screen.getByText("Third")).toBeInTheDocument();
  });

  it("applies reduced opacity to non-final transcripts", () => {
    const { container } = render(
      <TranscriptPanel
        transcripts={[{ speaker: "user", text: "partial", isFinal: false }]}
      />
    );
    const line = container.querySelector(".opacity-60");
    expect(line).toBeInTheDocument();
  });
});
