"use client";

import { ArrowUp, Mic } from "lucide-react";

export type AssistantInputProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value?: string) => void;
  onVoiceToggle: () => void;
  voiceActive: boolean;
  voiceSupported: boolean;
  disabled: boolean;
  placeholder: string;
};

export function InputBar({
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
      className={voiceActive ? "input-bar voice-active" : "input-bar"}
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
      <div className="input-actions">
        <span className="shortcut">⌘ K</span>
        <button
          className="icon-button mic-button"
          type="button"
          aria-label={voiceActive ? "Stop voice input" : "Voice input"}
          aria-pressed={voiceActive}
          disabled={!voiceSupported || disabled}
          onClick={onVoiceToggle}
        >
          <Mic size={24} strokeWidth={1.65} />
        </button>
        <button className="send-button" type="submit" aria-label="Send message" disabled={disabled || !value.trim()}>
          <ArrowUp size={24} strokeWidth={1.7} />
        </button>
      </div>
    </form>
  );
}
