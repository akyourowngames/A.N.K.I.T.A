"use client";

import {
  Box,
  CheckCircle2,
  ChevronDown,
  FileText,
  GitBranch,
  MessageSquare,
  Settings
} from "lucide-react";

const navItems = [
  { label: "Chat", icon: MessageSquare, view: "chat" },
  { label: "Memory", icon: GitBranch, view: "memory" },
  { label: "Tasks", icon: CheckCircle2 },
  { label: "Notes", icon: FileText },
  { label: "Tools", icon: Box },
  { label: "Settings", icon: Settings }
];

export function Sidebar({
  activeView = "chat",
  onViewChange
}: {
  activeView?: "chat" | "memory";
  onViewChange?: (view: "chat" | "memory") => void;
}) {
  return (
    <aside className="sidebar">
      <div className="assistant-mark" aria-hidden="true">
        <span />
      </div>

      <nav className="side-nav" aria-label="Primary">
        {navItems.map(({ label, icon: Icon, view }) => (
          <button
            className={view === activeView ? "nav-item active" : "nav-item"}
            type="button"
            key={label}
            onClick={() => {
              if (view === "chat" || view === "memory") {
                onViewChange?.(view);
              }
            }}
          >
            <Icon size={30} strokeWidth={1.75} />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      <button className="profile-switcher" type="button" aria-label="User menu">
        <span className="avatar" aria-hidden="true" />
        <ChevronDown size={17} strokeWidth={1.6} />
      </button>
    </aside>
  );
}
