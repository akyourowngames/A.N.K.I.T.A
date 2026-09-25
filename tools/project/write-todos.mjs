import { capOutput } from '../shared/_shared.mjs';

export const name = "write_todos";
export const description =
  "Track a multi-step session plan. Start with todos, then update existing items by stable id. " +
  "Existing items cannot be replaced or removed. Project tasks belong in project_memory.";

export const parameters = {
  type: "object",
  properties: {
    todos: {
      type: "array",
      description: "Initial checklist, or the existing checklist plus appended tasks. Existing text and order stay unchanged.",
      items: {
        type: "object",
        properties: {
          content: { type: "string", description: "What the step is." },
          id: { type: "string", description: "Stable ID of an existing step when resubmitting the list." },
          status: {
            type: "string",
            description: "One of: pending, in_progress, completed, cancelled.",
          },
          activeForm: { type: "string", description: "Present-continuous label, e.g. 'Writing tests'." },
        },
        required: ["content", "status"],
      },
    },
    updates: { type: "array", description: "Change statuses of existing steps without rewriting the list.", items: {
      type: "object", properties: { id: { type: "string" }, status: { type: "string" } }, required: ["id", "status"],
    } },
  },
};

export const needsApproval = false;

const STATUSES = new Set(["pending", "in_progress", "completed", "cancelled"]);

const MARK = { pending: " ", in_progress: ">", completed: "x", cancelled: "-" };

export function run(args, ctx = {}) {
  const state = ctx.state || (ctx.state = {});
  const current = state.todos || [];
  if (Array.isArray(args.updates)) {
    if (!args.updates.length) throw new Error('updates must be non-empty.');
    const seen = new Set();
    const next = current.map(item => ({ ...item }));
    for (const update of args.updates) {
      if (!update?.id || seen.has(update.id)) throw new Error('updates need unique existing task IDs.');
      seen.add(update.id);
      if (!STATUSES.has(update.status)) throw new Error('invalid todo status.');
      const target = next.find(item => item.id === update.id);
      if (!target) throw new Error(`unknown todo ID: ${update.id}. Available IDs: ${capOutput(current.map(item => item.id).join(', ') || '(none)', 2000)}.`);
      target.status = update.status;
      if (update.status === 'completed' && !target.completedAt) target.completedAt = new Date().toISOString();
    }
    state.todos = next;
    return render(next);
  }
  const list = args.todos;
  if (!Array.isArray(list) || !list.length) {
    throw new Error("todos must be a non-empty array.");
  }
  if (list.length < current.length) throw new Error(`cannot remove existing todos. Use status: cancelled instead. Current list:\n${capOutput(render(current), 2000)}`);
  const next = list.map((item, i) => {
    if (!item || typeof item.content !== "string" || !item.content.trim()) {
      throw new Error(`todos[${i}].content must be a non-empty string.`);
    }
    if (!STATUSES.has(item.status)) {
      throw new Error(`todos[${i}].status must be one of ${[...STATUSES].join(", ")}.`);
    }
    const prior = current[i];
    if (prior && (prior.content !== item.content || (item.id && item.id !== prior.id))) {
      throw new Error(`cannot replace or reorder existing todos; use updates with stable IDs. Current list:\n${capOutput(render(current), 2000)}`);
    }
    return {
      ...prior,
      id: prior?.id || `s${i + 1}`,
      at: prior?.at || new Date().toISOString(),
      content: prior?.content || item.content,
      status: item.status,
      ...(item.status === 'completed' && !prior?.completedAt ? { completedAt: new Date().toISOString() } : {}),
      activeForm: typeof item.activeForm === "string" ? item.activeForm : prior?.activeForm || item.content,
    };
  });
  state.todos = next;
  return render(next);
}

function render(todos) {
  return todos.map((t, i) => `[${MARK[t.status]}] ${i + 1}. ${t.content} (${t.id})`).join('\n');
}
