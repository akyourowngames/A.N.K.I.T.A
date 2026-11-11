export const ASSISTANT_ROUTINE_DIRECTORY = 'assistant-routines'; // Profile-local reusable requests; separate from enabled schedules.
export const ROUTINE_NAME_CHARS = 100; // Display characters; a long original instruction remains in its template.
export const ROUTINE_TEMPLATE_CHARS = 8000; // Characters, leaving room for values and execution guidance inside a tracked request.
export const ROUTINE_VALUE_BYTES = 4000; // Aggregate UTF-8 bytes of parameter values per run.
export const ROUTINE_PARAMETER_LIMIT = 16; // Named inputs per reusable request.
export const ROUTINE_PARAMETER_NAME_CHARS = 40; // ASCII identifier characters, not expressions or executable code.
export const ROUTINE_PARAMETER_PATTERN = /\{\{([A-Za-z][A-Za-z0-9_]*)\}\}/g;

export function routineParameterNames(template) {
  if (typeof template !== 'string' || !template.trim() || template.length > ROUTINE_TEMPLATE_CHARS) throw new Error(`Routine instructions need 1–${ROUTINE_TEMPLATE_CHARS} characters.`);
  const names = [...new Set([...template.matchAll(ROUTINE_PARAMETER_PATTERN)].map(match => match[1]))];
  const remaining = template.replace(ROUTINE_PARAMETER_PATTERN, '');
  if (remaining.includes('{{') || remaining.includes('}}') || names.some(name => name.length > ROUTINE_PARAMETER_NAME_CHARS) || names.length > ROUTINE_PARAMETER_LIMIT) throw new Error('Use simple {{parameter_name}} placeholders within the routine parameter limit.');
  return names;
}
