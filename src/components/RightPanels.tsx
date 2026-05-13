"use client";

import { AudioLines, Check, CheckCircle2, Circle, FileText } from "lucide-react";
import { motion } from "framer-motion";

const tasks = [
  { title: "Review quarterly report", meta: "Today" },
  { title: "Email design feedback", meta: "Done", complete: true },
  { title: "Plan weekend trip", meta: "Sat" }
];

const notes = [
  { title: "Project Aurora", meta: "Updated 2h ago" },
  { title: "Ideas backlog", meta: "Updated yesterday" },
  { title: "Book recommendations", meta: "Updated 3d ago" }
];

export function RightPanels() {
  return (
    <motion.aside
      className="right-panel-stack"
      initial={{ opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 28, filter: "blur(10px)" }}
      transition={{ duration: 0.75, delay: 0.12, ease: [0.22, 1, 0.36, 1] }}
    >
      <section className="glass-card tasks-card">
        <PanelHeader icon={<CheckCircle2 size={23} />} title="Tasks" action="View all" />
        <div className="card-list task-list">
          {tasks.map((task) => (
            <div className={task.complete ? "task-row complete" : "task-row"} key={task.title}>
              <span className="task-state" aria-hidden="true">
                {task.complete ? <Check size={14} strokeWidth={2.5} /> : <Circle size={20} />}
              </span>
              <span className="row-title">{task.title}</span>
              <span className="row-meta">{task.meta}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="glass-card notes-card">
        <PanelHeader icon={<FileText size={23} />} title="Notes" action="View all" />
        <div className="card-list notes-list">
          {notes.map((note) => (
            <div className="note-row" key={note.title}>
              <span className="row-title">{note.title}</span>
              <span className="row-meta">{note.meta}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="glass-card system-card">
        <PanelHeader icon={<AudioLines size={23} />} title="System" />
        <div className="system-list">
          <div className="system-row">
            <span>Model</span>
            <strong>Astra 3</strong>
          </div>
          <div className="system-row memory-row">
            <span>Memory</span>
            <div className="memory-track" aria-label="Memory 62 percent">
              <span />
            </div>
            <strong>62%</strong>
          </div>
          <div className="system-row">
            <span>Status</span>
            <strong className="online-state">
              <i />
              Online
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
  icon: React.ReactNode;
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
