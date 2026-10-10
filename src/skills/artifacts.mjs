import fs from 'node:fs';
import path from 'node:path';

/** Explicit roots may be links; contributed artifacts beneath them must be real files. */
export function skillArtifactPath(root, parts, { directory = false } = {}) {
  const realRoot = fs.realpathSync(root);
  const target = path.resolve(realRoot, ...parts);
  const relative = path.relative(realRoot, target);
  if (!relative || relative.startsWith(`..${path.sep}`) || relative === '..' || path.isAbsolute(relative)) throw new Error('artifact escapes skill root');
  const stat = fs.lstatSync(target);
  if (stat.isSymbolicLink() || path.relative(target, fs.realpathSync(target)) || !(directory ? stat.isDirectory() : stat.isFile())) throw new Error('artifact uses a link or is not a regular artifact');
  return target;
}
