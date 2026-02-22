import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import VoiceStatus from "@/components/VoiceStatus";

describe("VoiceStatus", () => {
  it("returns null when idle", () => {
    const { container } = render(<VoiceStatus status="idle" />);
    expect(container.firstChild).toBeNull();
  });

  it("shows Connecting... label", () => {
    render(<VoiceStatus status="connecting" />);
    expect(screen.getByText("Connecting...")).toBeInTheDocument();
  });

  it("shows Listening label", () => {
    render(<VoiceStatus status="listening" />);
    expect(screen.getByText("Listening")).toBeInTheDocument();
  });

  it("shows Thinking... label", () => {
    render(<VoiceStatus status="thinking" />);
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
  });

  it("shows Speaking label", () => {
    render(<VoiceStatus status="speaking" />);
    expect(screen.getByText("Speaking")).toBeInTheDocument();
  });

  it("shows Disconnecting... label", () => {
    render(<VoiceStatus status="disconnecting" />);
    expect(screen.getByText("Disconnecting...")).toBeInTheDocument();
  });

  it("has animated dots for non-idle statuses", () => {
    const { container } = render(<VoiceStatus status="listening" />);
    const dots = container.querySelectorAll(".animate-pulse");
    expect(dots.length).toBe(3);
  });
});
