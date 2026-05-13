"use client";

import { AudioLines } from "lucide-react";

export function StatusHeader({ title, detail }: { title: string; detail: string }) {
  return (
    <header className="status-header">
      <div className="status-title">
        <AudioLines size={22} strokeWidth={1.65} />
        <span>{title}</span>
      </div>
      <p>{detail}</p>
    </header>
  );
}
