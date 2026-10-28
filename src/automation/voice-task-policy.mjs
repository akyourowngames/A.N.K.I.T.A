// Shared settings are import-free so config can load without the agent/tool graph.
export const VOICE_TASK_DIRECTORY = 'voice-tasks'; // Subdirectory of CONFIG_DIR, separate from process jobs.
export const VOICE_TASK_LIMIT = 20; // Most recent delegated voice-task records retained.
export const VOICE_JOB_SPEAK_MIN_INTERVAL_MS = 2500; // Milliseconds between step announcements.
export const VOICE_SPEECH_GAP_MS = 300; // Milliseconds of breathing room between completed spoken clips.
export const VOICE_JOB_WAIT_UPDATE_MS = 10000; // Milliseconds: reassure during long work without flooding short turns.
export const VOICE_PROGRESS_PLAYBACK_MAX_MS = 15000; // Milliseconds: bound a stuck player for a maximum twenty-word update.
export const VOICE_PROGRESS_POLL_MS = 80; // Milliseconds: retry the newest update while an acknowledgement owns playback.
