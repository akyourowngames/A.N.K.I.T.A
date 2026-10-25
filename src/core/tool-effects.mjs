/**
 * Tools that can modify the workspace. Kept in one place so the turn audit and
 * the desktop workspace watcher agree on what counts as a change.
 */

// Image tools write into the workspace, but the paths they name are generated
// artifacts rather than project source, so the audit treats them separately.
export const GENERATED_ARTIFACT_TOOLS = Object.freeze(["image_generate", "image_download"]);

export const FILE_EFFECT_TOOLS = Object.freeze([
  "write_file",
  "edit_file",
  "edit_lines",
  "apply_patch",
  "move_file",
  "delete_file",
  "restore_file",
  ...GENERATED_ARTIFACT_TOOLS,
]);

// Commands and git can rewrite files without naming them, so the desktop still
// refreshes the file tree for these even though the audit cannot record paths.
export const WORKSPACE_EFFECT_TOOLS = Object.freeze([...FILE_EFFECT_TOOLS, "run_command", "job_stop", "git"]);

const FILE_EFFECTS = new Set(FILE_EFFECT_TOOLS);

export function isFileEffectTool(name) {
  return FILE_EFFECTS.has(String(name ?? ""));
}
