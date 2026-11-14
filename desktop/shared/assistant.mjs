export const ASSISTANT_ACTIONS = Object.freeze({
  today: 'assistantToday', resume: 'assistantResume', resolve: 'assistantResolve',
  memoryList: 'assistantMemoryList', memorySave: 'assistantMemorySave', memoryForget: 'assistantMemoryForget',
  projectSave: 'assistantProjectSave', projectForget: 'assistantProjectForget',
  commitmentComplete: 'assistantCommitmentComplete',
  routineList: 'assistantRoutineList', routineSave: 'assistantRoutineSave', routineRemove: 'assistantRoutineRemove',
  routineRun: 'assistantRoutineRun', routineSchedule: 'assistantRoutineSchedule',
  briefingSchedule: 'assistantBriefingSchedule',
});
export const ASSISTANT_CHANGED = 'assistant-task-changed'; // Views refresh from authoritative saved records.
export const KNOWLEDGE_CHANGED = 'assistant-knowledge-changed';
export const ASSISTANT_ROUTINES_CHANGED = 'assistant-routines-changed';
export const ASSISTANT_LIST_LIMIT = 30; // Rows per visible section; full history stays on disk.
export const MEMORY_TEXT_LIMIT = 4000; // Characters per user-authored fact or commitment.
export const RESUMABLE_TASK_STATES = Object.freeze(['interrupted', 'failed', 'cancelled', 'needs_review']);
