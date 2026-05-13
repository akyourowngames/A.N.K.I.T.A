"use client";

import { SlidersHorizontal } from "lucide-react";

export function MobileHeader() {
  return (
    <header className="mobile-header">
      <div className="mobile-assistant-mark" aria-hidden="true">
        <span />
      </div>

      <div className="mobile-brand">
        <h2>AURORA</h2>
        <p>
          <span />
          Online
        </p>
      </div>

      <button className="mobile-settings-button" type="button" aria-label="Settings">
        <SlidersHorizontal size={31} strokeWidth={1.65} />
      </button>
    </header>
  );
}
