import { createInterface } from 'node:readline/promises';
import { scaffoldSkill, SCAFFOLD_USAGE } from '../skills/scaffold.mjs';

/** Local commands run before provider bootstrap so authoring works offline. */
export async function runLocalCommand(argv, { ask, write = text => console.log(text) } = {}) {
  if (argv[0] !== 'new' || argv[1] !== 'skill') return false;
  const args = argv.slice(2);
  if (args.includes('--help')) { write(SCAFFOLD_USAGE); return true; }
  let name = args[0] && !args[0].startsWith('--') ? args.shift() : undefined;
  const options = parseLocalOptions(args, ['--permissions', '--example', '--directory']);
  let reader;
  const question = ask || (async prompt => {
    if (!process.stdin.isTTY) throw new Error(`Missing author input. Use ${SCAFFOLD_USAGE}`);
    reader ||= createInterface({ input: process.stdin, output: process.stdout });
    return reader.question(prompt);
  });
  try {
    name ??= (await question('Skill name: ')).trim();
    const rawPermissions = options['--permissions'] ?? await question('Access domains (files,network,shell,browser; blank for none): ');
    const example = options['--example'] ?? await question('One example input: ');
    const permissions = rawPermissions.split(',').map(value => value.trim()).filter(Boolean);
    const target = scaffoldSkill({ name, permissions, example, root: options['--directory'] });
    write(`Created skill: ${target}`);
    return true;
  } finally { reader?.close(); }
}

export function parseLocalOptions(args, allowed) {
  const result = {};
  for (let index = 0; index < args.length; index++) {
    const key = args[index];
    if (!allowed.includes(key) || Object.hasOwn(result, key)) throw new Error(`Unknown or repeated option: ${key}`);
    const value = args[++index];
    if (value === undefined || value.startsWith('--')) throw new Error(`${key} needs a value`);
    result[key] = value;
  }
  return result;
}
