import fs from 'node:fs';
import { resolvePath } from './_shared.mjs';

// The context belongs to one tool call. Do not share plans between concurrent
// approvals, and never rerun a preparation against changed bytes after consent.
const approved = new WeakMap();
const identity = ctx => JSON.stringify([ctx?.cwd, ctx?.workspacePath]);
function snapshot(p, expected) {
  try {
    const stat = fs.lstatSync(p);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Not a regular file: ${p}`);
    const bytes = fs.readFileSync(p);
    if (expected !== undefined && !bytes.equals(Buffer.from(expected))) throw new Error(`File changed while preparing approval: ${p}`);
    return { bytes, dev: stat.dev, ino: stat.ino, mode: stat.mode & 0o7777 };
  } catch (error) { if (error.code === 'ENOENT' && expected === undefined) return null; throw error; }
}

export function rememberPlan(name, args, ctx, plan) {
  if (!ctx || typeof ctx !== 'object') throw new Error('Approval requires a tool call context.');
  const snapshots = plan.error ? [] : plan.snapshots ? [...plan.snapshots] :
    [[plan.p, snapshot(plan.p, plan.file?.raw ?? plan.raw)]];
  if (plan.existed === false && snapshots[0]?.[1]) throw new Error('File appeared while preparing approval. Request approval again.');
  let plans = approved.get(ctx);
  if (!plans) approved.set(ctx, plans = new Map());
  plans.set(name, { plan, snapshots, arguments: JSON.stringify(args), context: identity(ctx), root: fs.realpathSync(ctx.workspacePath || ctx.cwd || process.cwd()) });
  return plan;
}

export function executionPlan(name, args, ctx, prepare) {
  const plans = ctx && approved.get(ctx), saved = plans?.get(name);
  if (!saved) return prepare(args, ctx);
  plans.delete(name);
  try {
    if (saved.arguments !== JSON.stringify(args) || saved.context !== identity(ctx)) throw new Error('Arguments or workspace changed after approval. Request approval again.');
    if (saved.root !== fs.realpathSync(ctx.workspacePath || ctx.cwd || process.cwd())) throw new Error('Workspace changed after approval. Request approval again.');
    if (saved.plan.error) return saved.plan;
    for (const [p, original] of saved.snapshots) {
      resolvePath(p, saved.plan.root ? { cwd: saved.plan.root } : ctx);
      const now = snapshot(p);
      if (Boolean(original) !== Boolean(now) || (original && (original.dev !== now.dev || original.ino !== now.ino || original.mode !== now.mode || !original.bytes.equals(now.bytes)))) {
        throw new Error(`File changed after approval: ${p}. Request approval again.`);
      }
    }
    return saved.plan;
  } catch (error) { return { error: error.message }; }
}
