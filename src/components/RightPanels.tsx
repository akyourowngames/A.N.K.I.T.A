"use client";

import { Activity, AudioLines, Music2 } from "lucide-react";
import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { useDashboardState } from "../hooks/useDashboardState";
import type { DashboardState } from "../lib/assistantClient";

export function RightPanels() {
  const { dashboard, offline } = useDashboardState();
  const music = dashboard?.music;
  const assistant = dashboard?.assistant;

  return (
    <motion.aside
      className="right-panel-stack"
      initial={{ opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 28, filter: "blur(10px)" }}
      transition={{ duration: 0.75, delay: 0.12, ease: [0.22, 1, 0.36, 1] }}
    >
      <section className="glass-card music-card">
        <PanelHeader icon={<Music2 size={23} />} title="Music" action={offline ? "Offline" : music?.status ?? "Syncing"} />
        <div className="music-now">
          <div className={music?.running ? "music-disc is-live" : "music-disc"} aria-hidden="true">
            <span />
          </div>
          <div className="music-copy">
            <span>{music?.running ? "Now playing" : music?.status === "Last played" ? "Last played" : "Player state"}</span>
            <strong>{music?.title ?? "Checking music state..."}</strong>
            <p>{musicDetail(music, offline)}</p>
          </div>
        </div>
        <div className="music-progress-row">
          <div className="music-progress" aria-label={`Playback ${music?.progress_percent ?? 0} percent`}>
            <span style={{ width: `${music?.progress_percent ?? 0}%` }} />
          </div>
          <em>{durationText(music)}</em>
        </div>
        <div className="music-metrics">
          <span>
            Queue <strong>{music?.queue_length ?? "-"}</strong>
          </span>
          <span>
            Vol <strong>{music?.volume != null ? `${music.volume}%` : "-"}</strong>
          </span>
          <span>
            Backend <strong>{music?.backend ?? "-"}</strong>
          </span>
        </div>
      </section>

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
          <div className="system-row memory-row">
            <span>Library</span>
            <div className="memory-track" aria-label={`${music?.library_tracks ?? 0} local tracks`}>
              <span style={{ width: libraryFill(music) }} />
            </div>
            <strong>{music?.library_tracks ?? "-"}</strong>
          </div>
          <div className="system-row">
            <span>Status</span>
            <strong className="online-state">
              <i />
              {offline ? "Waiting" : music?.running ? "Active" : "Ready"}
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

function musicDetail(music: DashboardState["music"] | undefined, offline: boolean) {
  if (offline) {
    return "FastAPI dashboard is not reachable.";
  }
  if (!music) {
    return "Reading Jarvis player state.";
  }
  const artist = music.artist || "Unknown artist";
  return `${artist} - ${music.source || "local"} - ${music.status}`;
}

function durationText(music: DashboardState["music"] | undefined) {
  if (!music?.duration_seconds) {
    return "Live";
  }
  return `${formatSeconds(music.elapsed_seconds)} / ${formatSeconds(music.duration_seconds)}`;
}

function formatSeconds(value: number) {
  const safeValue = Math.max(0, Math.floor(value));
  const minutes = Math.floor(safeValue / 60);
  const seconds = String(safeValue % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function libraryFill(music: DashboardState["music"] | undefined) {
  const tracks = music?.library_tracks ?? 0;
  if (tracks <= 0) {
    return "8%";
  }
  return `${Math.max(18, Math.min(100, tracks * 12))}%`;
}
