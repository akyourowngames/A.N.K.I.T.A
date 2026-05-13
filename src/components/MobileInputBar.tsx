"use client";

import { ArrowUp, Mic } from "lucide-react";

export function MobileInputBar() {
  return (
    <form className="mobile-input-bar">
      <input aria-label="Ask anything" placeholder="Ask anything..." />
      <div className="mobile-input-actions">
        <button type="button" aria-label="Voice input">
          <Mic size={31} strokeWidth={1.8} />
        </button>
        <span aria-hidden="true" />
        <button className="mobile-send-button" type="submit" aria-label="Send message">
          <ArrowUp size={33} strokeWidth={1.7} />
        </button>
      </div>
    </form>
  );
}
