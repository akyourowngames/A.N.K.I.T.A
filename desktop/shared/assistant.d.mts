export const ASSISTANT_ACTIONS: Readonly<Record<'today' | 'resume' | 'resolve' | 'memoryList' | 'memorySave' | 'memoryForget' | 'projectSave' | 'projectForget' | 'commitmentComplete' | 'routineList' | 'routineSave' | 'routineRemove' | 'routineRun' | 'routineSchedule', string>>;
export const ASSISTANT_CHANGED: 'assistant-task-changed';
export const KNOWLEDGE_CHANGED: 'assistant-knowledge-changed';
export const ASSISTANT_ROUTINES_CHANGED: 'assistant-routines-changed';
export const ASSISTANT_LIST_LIMIT: number;
export const MEMORY_TEXT_LIMIT: number;
export const RESUMABLE_TASK_STATES: readonly string[];
