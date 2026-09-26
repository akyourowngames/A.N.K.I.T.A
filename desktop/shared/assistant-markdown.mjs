export function formatAssistantMarkdown(value) {
  let markdown = String(value ?? '');
  const wrapped = /^\s*```(?:md|markdown)\s*\n([\s\S]*)\n```\s*$/i.exec(markdown);
  if (wrapped) markdown = wrapped[1];

  const lines = markdown.split(/\r?\n/);
  const output = [];
  let fence = null;
  for (let i = 0; i < lines.length;) {
    const marker = /^ {0,3}(`{3,}|~{3,})/.exec(lines[i]);
    if (marker) {
      const char = marker[1][0];
      if (!fence) fence = { char, width: marker[1].length };
      else if (fence.char === char && marker[1].length >= fence.width) fence = null;
      output.push(lines[i++]);
      continue;
    }
    if (fence || /^(?: {4}|\t)/.test(lines[i])) {
      output.push(lines[i++]);
      continue;
    }

    const label = /^([A-Z][^:!?]{2,70}):$/.exec(lines[i].trim());
    if (label && (i === 0 || !lines[i - 1].trim())) {
      output.push(`### ${label[1]}`);
      if (lines[i + 1]?.trim()) output.push('');
      i++;
      continue;
    }
    if (/^ {0,3}[•●◦]\s+/.test(lines[i])) {
      output.push(lines[i++].replace(/^([ ]{0,3})[•●◦]\s+/, '$1- '));
      continue;
    }
    if (!lines[i].includes('\t')) {
      output.push(lines[i++]);
      continue;
    }

    const rows = [];
    while (i + rows.length < lines.length && lines[i + rows.length].includes('\t') && !/^(?: {4}|\t)/.test(lines[i + rows.length])) {
      rows.push(lines[i + rows.length].split('\t').map(cell => cell.trim()));
    }
    const columns = rows[0]?.length || 0;
    if (rows.length >= 2 && columns >= 2 && columns <= 6 && rows.every(row => row.length === columns)) {
      const row = cells => `| ${cells.map(cell => cell.replace(/\|/g, '\\|')).join(' | ')} |`;
      output.push(row(rows[0]), row(Array(columns).fill('---')), ...rows.slice(1).map(row));
    } else {
      output.push(...lines.slice(i, i + rows.length));
    }
    i += rows.length;
  }
  return output.join('\n');
}
