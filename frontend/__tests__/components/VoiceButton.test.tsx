import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VoiceButton from "@/components/VoiceButton";

describe("VoiceButton", () => {
  it("shows start title when idle", () => {
    render(
      <VoiceButton
        isActive={false}
        status="idle"
        onStart={vi.fn()}
        onEnd={vi.fn()}
      />
    );
    expect(screen.getByTitle("Start voice session")).toBeInTheDocument();
  });

  it("shows end title when active", () => {
    render(
      <VoiceButton
        isActive={true}
        status="listening"
        onStart={vi.fn()}
        onEnd={vi.fn()}
      />
    );
    expect(screen.getByTitle("End voice session")).toBeInTheDocument();
  });

  it("calls onStart when clicked while idle", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    render(
      <VoiceButton
        isActive={false}
        status="idle"
        onStart={onStart}
        onEnd={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button"));
    expect(onStart).toHaveBeenCalledOnce();
  });

  it("calls onEnd when clicked while active", async () => {
    const user = userEvent.setup();
    const onEnd = vi.fn();
    render(
      <VoiceButton
        isActive={true}
        status="listening"
        onStart={vi.fn()}
        onEnd={onEnd}
      />
    );

    await user.click(screen.getByRole("button"));
    expect(onEnd).toHaveBeenCalledOnce();
  });

  it("is disabled during connecting", () => {
    render(
      <VoiceButton
        isActive={false}
        status="connecting"
        onStart={vi.fn()}
        onEnd={vi.fn()}
      />
    );
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("is disabled during disconnecting", () => {
    render(
      <VoiceButton
        isActive={true}
        status="disconnecting"
        onStart={vi.fn()}
        onEnd={vi.fn()}
      />
    );
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("shows pulse indicator when active and not connecting", () => {
    const { container } = render(
      <VoiceButton
        isActive={true}
        status="listening"
        onStart={vi.fn()}
        onEnd={vi.fn()}
      />
    );
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });
});
