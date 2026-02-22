import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MessageBubble from "@/components/MessageBubble";
import type { ChatMessage } from "@/hooks/useChat";

function makeMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m1",
    role: "user",
    content: "Hello",
    source: "text",
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("MessageBubble", () => {
  it("renders user message with blue styling", () => {
    const { container } = render(<MessageBubble message={makeMsg()} />);
    const bubble = container.querySelector(".bg-blue-600");
    expect(bubble).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("renders assistant message with gray styling", () => {
    const { container } = render(
      <MessageBubble message={makeMsg({ role: "assistant" })} />
    );
    const bubble = container.querySelector(".bg-gray-100");
    expect(bubble).toBeInTheDocument();
  });

  it("shows voice badge for voice messages", () => {
    render(<MessageBubble message={makeMsg({ source: "voice" })} />);
    expect(screen.getByText("voice")).toBeInTheDocument();
  });

  it("hides voice badge for text messages", () => {
    render(<MessageBubble message={makeMsg({ source: "text" })} />);
    expect(screen.queryByText("voice")).not.toBeInTheDocument();
  });
});
