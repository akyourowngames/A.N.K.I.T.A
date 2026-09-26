import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatAssistantMarkdown } from '../../desktop/shared/assistant-markdown.mjs';

test('a whole-response Markdown fence displays as Markdown', () => {
  assert.equal(formatAssistantMarkdown('```markdown\n## Plan\n\n- First\n- Second\n```'), '## Plan\n\n- First\n- Second');
});

test('tab-separated model rows become a GFM table without losing surrounding prose', () => {
  const answer = 'Morning flights:\n\nAirline\tTime\tPrice\nAir India\t08:30\t₹7,200\nIndiGo\t09:20\t₹7,500\n\nChoose a flight.';
  assert.equal(formatAssistantMarkdown(answer), '### Morning flights\n\n| Airline | Time | Price |\n| --- | --- | --- |\n| Air India | 08:30 | ₹7,200 |\n| IndiGo | 09:20 | ₹7,500 |\n\nChoose a flight.');
});

test('normalization preserves actual code fences and existing Markdown tables', () => {
  const answer = '```ts\nconst values = "a\tb";\n```\n\n| Name | Value |\n| --- | --- |\n| A | B |';
  assert.equal(formatAssistantMarkdown(answer), answer);
});

test('plain section labels and bullet glyphs gain Markdown structure', () => {
  const answer = 'Why I stopped:\n\n• The page needs sign-in\n• No account was connected';
  assert.equal(formatAssistantMarkdown(answer), '### Why I stopped\n\n- The page needs sign-in\n- No account was connected');
});

test('indented code containing tabs stays code', () => {
  const answer = '    first\tsecond\n    third\tfourth';
  assert.equal(formatAssistantMarkdown(answer), answer);
});

test('a plain label followed directly by prose becomes a section', () => {
  assert.equal(formatAssistantMarkdown('Next step:\nChoose a morning flight.'), '### Next step\n\nChoose a morning flight.');
});

test('the normalized answer renders as headings, lists, and a table', () => {
  const answer = 'Summary:\n\n• One result\n\nName\tPrice\nFlight\t₹7,200';
  const html = renderToStaticMarkup(React.createElement(ReactMarkdown, { remarkPlugins: [remarkGfm] }, formatAssistantMarkdown(answer)));
  assert.match(html, /<h3>Summary<\/h3>/);
  assert.match(html, /<ul>[\s\S]*<li>One result<\/li>[\s\S]*<\/ul>/);
  assert.match(html, /<table>.*<th>Name<\/th>.*<td>Flight<\/td>.*<\/table>/);
});
