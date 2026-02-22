import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatWindow from "@/components/ChatWindow";
import type { ChatMessage } from "@/hooks/useChat";

function makeMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m1",
    role: "user",
    content: "Test message",
    source: "text",
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ChatWindow", () => {
  it("renders messages", () => {
    const messages = [
      makeMsg({ id: "1", content: "Hello" }),
      makeMsg({ id: "2", role: "assistant", content: "Hi there" }),
    ];
    render(<ChatWindow messages={messages} loading={false} onSend={vi.fn()} />);
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Hi there")).toBeInTheDocument();
  });

  it("shows empty state placeholder", () => {
    render(<ChatWindow messages={[]} loading={false} onSend={vi.fn()} />);
    expect(screen.getByText("Start a conversation...")).toBeInTheDocument();
  });

  it("shows loading indicator", () => {
    const { container } = render(
      <ChatWindow messages={[]} loading={true} onSend={vi.fn()} />
    );
    const dots = container.querySelectorAll(".animate-bounce");
    expect(dots.length).toBe(3);
  });

  it("calls onSend and clears input on form submit", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatWindow messages={[]} loading={false} onSend={onSend} />);

    const input = screen.getByPlaceholderText("Type a message...");
    await user.type(input, "Hello world");
    await user.click(screen.getByText("Send"));

    expect(onSend).toHaveBeenCalledWith("Hello world");
    expect(input).toHaveValue("");
  });

  it("disables send button when loading", () => {
    render(<ChatWindow messages={[]} loading={true} onSend={vi.fn()} />);
    expect(screen.getByText("Send")).toBeDisabled();
  });

  it("disables send button when input is empty", () => {
    render(<ChatWindow messages={[]} loading={false} onSend={vi.fn()} />);
    expect(screen.getByText("Send")).toBeDisabled();
  });
});
