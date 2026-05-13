"use client";

import { Box, CheckCircle2, FileText } from "lucide-react";

const actions = [
  { label: "Tasks", icon: CheckCircle2 },
  { label: "Notes", icon: FileText },
  { label: "Tools", icon: Box }
];

export function MobileQuickActions() {
  return (
    <nav className="mobile-quick-actions" aria-label="Quick actions">
      {actions.map(({ label, icon: Icon }) => (
        <button type="button" key={label}>
          <Icon size={27} strokeWidth={1.65} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
