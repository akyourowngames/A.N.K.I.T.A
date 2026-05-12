"use client";

import { ArrowUp, Mic } from "lucide-react";

export function InputBar() {
  return (
    <form className="input-bar">
      <input aria-label="Ask anything" placeholder="Ask anything..." />
      <div className="input-actions">
        <span className="shortcut">⌘ K</span>
        <button className="icon-button mic-button" type="button" aria-label="Voice input">
          <Mic size={24} strokeWidth={1.65} />
        </button>
        <button className="send-button" type="submit" aria-label="Send message">
          <ArrowUp size={24} strokeWidth={1.7} />
        </button>
      </div>
    </form>
  );
}
