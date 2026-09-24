const MARK_STATUS = { ' ': 'pending', '>': 'in_progress', x: 'completed', '-': 'cancelled' };
const STATUSES = new Set(Object.values(MARK_STATUS));

function fromResult(result) {
  return result.split(/\r?\n(?=\[[ >x-]\] \d+\. )/).map(line => {
    const match = /^\[([ >x-])\] \d+\. ([\s\S]+) \((s\d+)\)$/.exec(line);
    return match ? { id: match[3], content: match[2], activeForm: match[2], status: MARK_STATUS[match[1]] } : null;
  }).filter(Boolean);
}

/** Rebuild the latest session plan from completed write_todos calls in one thread. */
export function todoProgress(messages) {
  let todos = [];
  for (const message of messages) {
    if (message.role === 'user') {
      const controlNote = typeof message.content === 'string' && (
        message.content.startsWith('(the runtime stopped the tool loop:') ||
        message.content === '(previous action was cancelled by the user)'
      );
      if (!controlNote) todos = [];
      continue;
    }
    if (message.role !== 'tool' || message.name !== 'write_todos' || message.isError || !message.result?.trim()) continue;
    const args = message.args;
    if (Array.isArray(args?.todos)) {
      todos = args.todos.filter(item => item && typeof item.content === 'string' && STATUSES.has(item.status)).map((item, index) => ({
        id: item.id || todos[index]?.id || `s${index + 1}`,
        content: item.content,
        activeForm: typeof item.activeForm === 'string' && item.activeForm.trim() ? item.activeForm : todos[index]?.content === item.content ? todos[index].activeForm : item.content,
        status: item.status,
      }));
    } else if (Array.isArray(args?.updates) && todos.length) {
      const updates = new Map(args.updates.map(item => [item.id, item.status]));
      todos = todos.map(item => ({ ...item, status: STATUSES.has(updates.get(item.id)) ? updates.get(item.id) : item.status }));
    } else {
      // A loaded thread can start after the original plan call. Tool output contains the full snapshot.
      const recovered = fromResult(message.result.trim());
      if (recovered.length) todos = recovered;
    }
  }
  return todos;
}
