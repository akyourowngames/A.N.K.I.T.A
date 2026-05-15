"use client";

import { Activity, AudioLines } from "lucide-react";
import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { useDashboardState } from "../hooks/useDashboardState";

export function RightPanels() {
  const { dashboard, offline } = useDashboardState();
  const assistant = dashboard?.assistant;

  return (
    <motion.aside
      className="right-panel-stack"
      initial={{ opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 28, filter: "blur(10px)" }}
      transition={{ duration: 0.75, delay: 0.12, ease: [0.22, 1, 0.36, 1] }}
    >
      <section className="glass-card assistant-card">
        <PanelHeader icon={<Activity size={23} />} title="Assistant" action={assistant?.streaming ? "Streaming" : "Ready"} />
        <div className="dashboard-list">
          <DashboardRow label="Model" value={assistant?.model ?? "Checking..."} />
          <DashboardRow label="Tools" value={assistant ? String(assistant.tools) : "-"} />
          <DashboardRow label="Mode" value={assistant?.streaming ? "Live stream" : "Request reply"} />
        </div>
      </section>

      <section className="glass-card system-card">
        <PanelHeader icon={<AudioLines size={23} />} title="System" />
        <div className="system-list">
          <div className="system-row">
            <span>API</span>
            <strong>{offline ? "Offline" : dashboard?.ok ? "Online" : "Checking"}</strong>
          </div>
          <div className="system-row">
            <span>Status</span>
            <strong className="online-state">
              <i />
              {offline ? "Waiting" : dashboard?.ok ? "Ready" : "Checking"}
            </strong>
          </div>
        </div>
      </section>
    </motion.aside>
  );
}

function PanelHeader({
  icon,
  title,
  action
}: {
  icon: ReactNode;
  title: string;
  action?: string;
}) {
  return (
    <div className="panel-header">
      <div>
        <span className="panel-icon">{icon}</span>
        <h2>{title}</h2>
      </div>
      {action ? <button type="button">{action}</button> : null}
    </div>
  );
}

function DashboardRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="dashboard-row">
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

