"use client";

import {
  Box,
  CheckCircle2,
  ChevronDown,
  FileText,
  MessageSquare,
  Settings
} from "lucide-react";

const navItems = [
  { label: "Chat", icon: MessageSquare, active: true },
  { label: "Tasks", icon: CheckCircle2 },
  { label: "Notes", icon: FileText },
  { label: "Tools", icon: Box },
  { label: "Settings", icon: Settings }
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="assistant-mark" aria-hidden="true">
        <span />
      </div>

      <nav className="side-nav" aria-label="Primary">
        {navItems.map(({ label, icon: Icon, active }) => (
          <button
            className={active ? "nav-item active" : "nav-item"}
            type="button"
            key={label}
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
