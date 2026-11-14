import { ASSISTANT_ACTIONS } from '../shared/assistant.mjs';

/** Called only after the main process has authenticated the application window. */
export async function runAssistantAction({ engine, action, payload = {} }) {
  const assistant = engine.assistant();
  switch (action) {
    case ASSISTANT_ACTIONS.today: return { ...assistant.today(), memories: assistant.memoryList(), routines: await assistant.routineList() };
    case ASSISTANT_ACTIONS.resume: return assistant.resume(payload);
    case ASSISTANT_ACTIONS.resolve: return assistant.resolve(payload);
    case ASSISTANT_ACTIONS.memoryList: return assistant.memoryList(payload);
    case ASSISTANT_ACTIONS.memorySave: return assistant.memorySave(payload);
    case ASSISTANT_ACTIONS.memoryForget: return assistant.memoryForget(payload);
    case ASSISTANT_ACTIONS.projectSave: return engine.editProjectRecord(payload);
    case ASSISTANT_ACTIONS.projectForget: return engine.editProjectRecord({ ...payload, forget: true });
    case ASSISTANT_ACTIONS.commitmentComplete: return engine.completeProjectTodo(payload.id, payload.ref);
    case ASSISTANT_ACTIONS.routineList: return assistant.routineList();
    case ASSISTANT_ACTIONS.routineSave: return assistant.routineSave(payload);
    case ASSISTANT_ACTIONS.routineRemove: return assistant.routineRemove(payload);
    case ASSISTANT_ACTIONS.routineRun: return assistant.routineRun(payload);
    case ASSISTANT_ACTIONS.routineSchedule: return assistant.routineSchedule(payload);
    case ASSISTANT_ACTIONS.briefingSchedule: return assistant.briefingSchedule(payload);
    default: throw new Error('Unknown assistant action.');
  }
}
