import { FLAGS, SLASH_GROUPS, LOCAL_COMMANDS } from './commands.mjs';
import { loadSkills } from './skills.mjs';
import { buildIndex } from '../palette/index.mjs';

const DESKTOP_ONLY = 'Desktop only'; // Honest availability labels for unequal surfaces.
const TERMINAL_ONLY = 'Terminal only';
const cell = value => String(value || '').replace(/\s+/g, ' ').replace(/\|/g, '\\|').replace(/`/g, "'");

/** Generated from executable command metadata and the real desktop palette index. */
export function commandCheatSheet({ query = '', skills = loadSkills() } = {}) {
  const index = buildIndex({ skills });
  const paletteLabel = entry => `Ctrl+K → ${entry.title}`;
  const rows = SLASH_GROUPS.flatMap(group => group.items.map(item => {
    const desktop = index.find(entry => entry.source === 'command' && entry.command === item.desktopCommand);
    return { terminal: `${item.name} ${item.args || ''}`.trim(), desktop: desktop ? paletteLabel(desktop) : TERMINAL_ONLY, description: item.desc, keywords: item.aliases || [] };
  }));
  rows.push(...FLAGS.map(flag => ({ terminal: `ankita ${flag.long} ${flag.value || ''}`.trim(), desktop: TERMINAL_ONLY, description: flag.desc, keywords: [flag.short || ''] })));
  rows.push(...LOCAL_COMMANDS.map(item => ({ terminal: `ankita ${item.name} ${item.args || ''}`.trim(), desktop: TERMINAL_ONLY, description: item.desc, keywords: [] })));
  rows.push(...index.map(entry => ({ terminal: entry.source === 'skill' ? `/skills → ${entry.skill}` : DESKTOP_ONLY, desktop: paletteLabel(entry), description: entry.hint, keywords: entry.keywords || [] })));
  const wanted = String(query).trim().toLocaleLowerCase();
  const visible = rows.filter(row => [row.terminal, row.desktop, row.description, ...row.keywords].join(' ').toLocaleLowerCase().includes(wanted));
  return ['# ANKITA command cheat sheet', '', 'Generated from the terminal registry and current desktop palette. Terminal-only entries have no direct palette action.', '', '| Terminal | Desktop / palette | What it does |', '| --- | --- | --- |', ...visible.map(row => `| ${cell(row.terminal)} | ${cell(row.desktop)} | ${cell(row.description)} |`), ...(visible.length ? [] : ['| No matching commands | | Try another keyword |'])].join('\n');
}
