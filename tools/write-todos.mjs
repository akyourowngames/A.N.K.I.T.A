export const name = "write_todos";
export const description =
  "Track a multi-step plan as a checklist. Replaces the whole list each call, so include " +
  "unchanged items too. Use it for tasks with three or more steps to show progress.";

export const parameters = {
  type: "object",
  properties: {
    todos: {
      type: "array",
      description: "The complete new checklist.",
      items: {
        type: "object",
        properties: {
          content: { type: "string", description: "What the step is." },
          status: {
            type: "string",
            description: "One of: pending, in_progress, completed, cancelled.",
          },
          activeForm: { type: "string", description: "Present-continuous label, e.g. 'Writing tests'." },
        },
        required: ["content", "status"],
      },
    },
  },
  required: ["todos"],
};

export const needsApproval = false;

const STATUSES = new Set(["pending", "in_progress", "completed", "cancelled"]);

const MARK = { pending: " ", in_progress: ">", completed: "x", cancelled: "-" };

export function run(args, ctx = {}) {
  const list = args.todos;
  if (!Array.isArray(list) || !list.length) {
    throw new Error("todos must be a non-empty array.");
  }
  const next = list.map((item, i) => {
    if (!item || typeof item.content !== "string" || !item.content.trim()) {
      throw new Error(`todos[${i}].content must be a non-empty string.`);
    }
    if (!STATUSES.has(item.status)) {
      throw new Error(`todos[${i}].status must be one of ${[...STATUSES].join(", ")}.`);
    }
    return {
      content: item.content,
      status: item.status,
      activeForm: typeof item.activeForm === "string" ? item.activeForm : item.content,
    };
  });
  const state = ctx.state || (ctx.state = {});
  state.todos = next;
  return next.map((t, i) => `[${MARK[t.status]}] ${i + 1}. ${t.content}`).join("\n");
}
