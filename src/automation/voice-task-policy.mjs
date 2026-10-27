// Shared settings are import-free so config can load without the agent/tool graph.
export const VOICE_TASK_DIRECTORY = 'voice-tasks'; // Subdirectory of CONFIG_DIR, separate from process jobs.
export const VOICE_TASK_LIMIT = 20; // Most recent delegated voice-task records retained.
export const VOICE_JOB_SPEAK_MIN_INTERVAL_MS = 2500; // Milliseconds between step announcements.
