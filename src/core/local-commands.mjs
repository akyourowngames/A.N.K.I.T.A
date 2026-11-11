import { createInterface } from 'node:readline/promises';
import path from 'node:path';
import { scaffoldSkill, SCAFFOLD_USAGE } from '../skills/scaffold.mjs';
import { commandCheatSheet } from './cheat-sheet.mjs';
import { RoutineStore } from '../automation/routines.mjs';
import { CONFIG_DIR, STATE_FILE, SESSIONS_DIR, loadConfig } from './config.mjs';
import { AssistantTaskStore, ASSISTANT_TASK_DIRECTORY } from '../assistant/tasks.mjs';
import { enableJobTemplate, jobTemplatesText } from '../automation/templates.mjs';
import { jobRunbook } from '../automation/runbooks.mjs';
import { JOB_BROWSER_DIRECTORY } from '../automation/job-policy.mjs';
import { SkillManager, SKILL_MANAGER_USAGE } from '../skills/manager.mjs';

/** Local commands run before provider bootstrap so authoring works offline. */
export async function runLocalCommand(argv, { ask, write = text => console.log(text), skillManager, assistantTasks } = {}) {
  if (argv[0] === 'work') {
    const store = assistantTasks || new AssistantTaskStore({ directory: path.join(CONFIG_DIR, ASSISTANT_TASK_DIRECTORY) });
    store.recoverInterrupted();
    if (argv[1] === 'list' && argv.length === 2) write(JSON.stringify(store.list()));
    else if (argv[1] === 'show' && argv.length === 3) write(JSON.stringify(store.get(argv[2])));
    else throw new Error('Usage: ankita work list | ankita work show <task-id> | ankita --resume-task <task-id>');
    return true;
  }
  if (argv[0] === 'skills') {
    const action = argv[1];
    if (!action || action === '--help') { write(SKILL_MANAGER_USAGE); return true; }
    const manager = skillManager || new SkillManager();
    let result;
    if (action === 'list' && argv.length === 2) result = manager.list();
    else if (action === 'search') result = await manager.search(argv.slice(2).join(' '));
    else if (action === 'preview' || action === 'install') {
      const options = parseLocalOptions(argv.slice(4), action === 'preview' ? ['--ref', '--path'] : ['--commit', '--path', '--sha256']);
      const selection = { source: argv[2], name: argv[3], ref: options['--ref'], path: options['--path'], commit: options['--commit'], sha256: options['--sha256'] };
      result = action === 'preview' ? await manager.preview(selection) : await manager.install(selection);
    } else throw new Error(`Usage: ${SKILL_MANAGER_USAGE}`);
    write(JSON.stringify(result));
    return true;
  }
  if (argv[0] === 'commands') { write(commandCheatSheet({ query: argv.slice(1).join(' ') })); return true; }
  if (argv[0] === 'runbook') {
    const options = parseLocalOptions(argv.slice(2), ['--state-file', '--runs-dir', '--time-zone']);
    const routine = new RoutineStore(options['--state-file'] || STATE_FILE).load().findRoutine(argv[1]);
    write(jobRunbook(routine, { runsDir: options['--runs-dir'] || path.join(SESSIONS_DIR, JOB_BROWSER_DIRECTORY), timeZone: options['--time-zone'] || loadConfig().timeZone }));
    return true;
  }
  if (argv[0] === 'jobs' && argv[1] === 'templates') {
    if (argv.length !== 2) throw new Error('Usage: ankita jobs templates');
    write(jobTemplatesText()); return true;
  }
  if (argv[0] === 'jobs' && argv[1] === 'enable') {
    const options = parseLocalOptions(argv.slice(3), ['--cron', '--channel', '--topic', '--url', '--state-file']);
    const job = enableJobTemplate(new RoutineStore(options['--state-file'] || STATE_FILE).load(), argv[2], {
      cron: options['--cron'], channel: options['--channel'], topic: options['--topic'], url: options['--url'],
    });
    write(`Enabled ${job.id}: ${job.cron} → ${job.channel}. It runs while the configured scheduler is active.`);
    return true;
  }
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
    const target = scaffoldSkill({ name, permissions, example, root: options['--directory'], registerRoot: options['--directory'] !== undefined });
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
