// These retain discovery, personal memory and the current task checklist during any focused workflow.
const SHARED_FOCUS_TOOLS = new Set(['find_tools', 'recall', 'remember', 'write_todos', 'skill']);
export const BROWSER_DISCOVERY_GUIDANCE = 'For interactive page work, start with find_tools(query="browser"). Use current browser observations for actions. If browser focus is active, restore scope="general" before files, shell or API work; memory and the conversation stay available.'; // Short pre-discovery affordance; full workflow instructions remain progressive.
export const TOOL_FOCUS_GUIDANCE = 'For an interactive website task, call find_tools(query="browser", scope="focus") and complete the workflow through browser tools. Focus keeps this same conversation, memory and approvals while withholding unrelated tools. To use files, shell or APIs for another part of the task, call find_tools with scope="general" and the needed group. Never claim browser work from HTTP/API evidence. Actions already return fresh snapshots; batch related form fields, do not repeat successful mutations, and verify item identity, stock and exact quantities before checkout.';
export function focusAllows(state, name) { return !state?.toolFocus || SHARED_FOCUS_TOOLS.has(name) || state.toolFocus.has(name); }
export function setToolFocus(state, scope, names) {
  if (!state || scope === undefined) return '';
  const before = state.toolFocus ? [...state.toolFocus].sort().join(',') : null;
  const after = scope === 'general' ? null : [...new Set(names)].sort().join(',');
  if (before !== after) (state.toolFocusTransitions ??= []).push({ scope, tools: scope === 'general' ? [] : [...new Set(names)] });
  if (scope === 'general') { state.toolFocus = null; return 'General tool access restored in the same session.'; }
  state.toolFocus = new Set(names);
  return `Tool focus active: ${names.join(', ')}. Memory, checklist and discovery remain available. Use find_tools(scope="general", query=the needed group) before changing methods.`;
}
