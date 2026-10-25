/**
 * Prompt addendum used only while a project is active. It narrows, never
 * replaces, the general "summarise and stop" rule.
 */
export const PROJECT_WORK_GUIDANCE =
  "PROJECT MEMORY\n" +
  "Work in this folder is logged automatically after each turn; do not narrate it or restate your reply to record it. " +
  "If the user explicitly states a decision or an open task, capture it with at most one project_memory call that turn " +
  "(action=decide or action=todo). Do not invent project facts, do not log progress notes, and do not add a tool round " +
  "just to update memory. The rule to summarise and stop still applies.";

export const UNTRACKED_REPO_GUIDANCE =
  "This folder is a git repository with no matching project. If it is relevant, offer once to track it with the project " +
  "tool; never create a project without the user agreeing.";
