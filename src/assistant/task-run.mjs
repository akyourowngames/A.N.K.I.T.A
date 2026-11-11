import { get, isReadOnly } from '../../tools/index.mjs';
import { runtimeVoiceTool, runtimeToolFlag } from '../core/runtime-tools.mjs';
import { isMutation } from '../core/verify.mjs';
import { recoveryPrompt } from './tasks.mjs';
import { snapshotAttachedContext, mergeAttachedContext } from './context.mjs';

/** Bind one admitted foreground request to the shared, after-approval tool boundary. */
export function beginAssistantTask(agent, text, options) {
  const context = agent.toolContext;
  if (context?.assistantTaskRun || agent.depth > 0 || !context?.assistantTasks || typeof text !== 'string' || !text.trim()) return null;
  const store = context.assistantTasks, ownerId = context.assistantOwnerId;
  const resumed = Boolean(options.assistantTaskId);
  const selected = options.assistantContext ?? snapshotAttachedContext(options.attachments);
  const previous = resumed && selected ? store.get(options.assistantTaskId, { ownerId }) : null;
  const record = resumed ? store.resume(options.assistantTaskId, { ownerId, context: selected ? mergeAttachedContext(previous?.context, selected) : undefined })
    : store.start(store.create({ ownerId, goal: options.assistantGoal ?? text, projectId: agent.projectId, workspacePath: agent.workspacePath || agent.cwd,
      provider: options.assistantProvider ?? agent.config?.provider ?? null,
      sourceTaskId: options.assistantSourceTaskId, routineId: options.assistantRoutineId,
      surface: options.assistantSurface ?? context.assistantSurface, context: selected }).id, { ownerId });
  const notify = task => {
    // Observers render progress; an observer failure cannot change execution or a saved receipt.
    try { context.onAssistantTask?.(task); options.onAssistantTask?.(task); } catch {}
    return task;
  };
  const mutation = (call, ctx) => {
    if (get(call.name)) return !isReadOnly(call.name, call.arguments, ctx);
    const runtime = runtimeVoiceTool(ctx, call.name);
    return runtime ? runtimeToolFlag(runtime, 'readOnly', call.arguments, ctx) !== true
      : isMutation(call.name, call.arguments, ctx.mcp);
  };
  const run = {
    id: record.id,
    requested(call, ctx) { return notify(store.requested(record.id, call, { mutation: mutation(call, ctx) })); },
    guard(call, ctx) { return store.guard(record.id, call, { mutation: mutation(call, ctx) }); },
    started(call) { return notify(store.started(record.id, call)); },
    settled(call, result) { return notify(store.settled(record.id, call, result)); },
    checklist(items) { return notify(store.checklist(record.id, items)); },
    finish(result) { return notify(store.finish(record.id, result)); },
    scope(namespace) {
      const scoped = call => ({ ...call, id: `${namespace}:${call.id}` });
      return { id: record.id, requested: (call, ctx) => run.requested(scoped(call), ctx),
        guard: (call, ctx) => run.guard(scoped(call), ctx), started: call => run.started(scoped(call)),
        settled: (call, result) => run.settled(scoped(call), result), checklist: () => {} };
    },
  };
  notify(record);
  return { run, text: resumed ? recoveryPrompt(record) : text, record };
}
