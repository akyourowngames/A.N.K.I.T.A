"use client";

import { ArrowUp, Mic } from "lucide-react";
import type { AssistantInputProps } from "./InputBar";

export function MobileInputBar({
  value,
  onChange,
  onSubmit,
  onVoiceToggle,
  voiceActive,
  voiceSupported,
  disabled,
  placeholder
}: AssistantInputProps) {
  return (
    <form
      className={voiceActive ? "mobile-input-bar voice-active" : "mobile-input-bar"}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <input
        aria-label="Ask anything"
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        value={value}
      />
      <div className="mobile-input-actions">
        <button
          type="button"
          aria-label={voiceActive ? "Stop voice input" : "Voice input"}
          aria-pressed={voiceActive}
          disabled={!voiceSupported || disabled}
          onClick={onVoiceToggle}
        >
          <Mic size={31} strokeWidth={1.8} />
        </button>
        <span aria-hidden="true" />
        <button className="mobile-send-button" type="submit" aria-label="Send message" disabled={disabled || !value.trim()}>
          <ArrowUp size={33} strokeWidth={1.7} />
        </button>
      </div>
    </form>
  );
}
