#!/usr/bin/env node
/**
 * Latency benchmark for the real agent loop.
 *
 * Drives the same Agent / provider / memory-recall path the REPL uses, timing
 * each phase of a turn so "why is it slow" has an answer beyond a total:
 *
 *   pre   recall lookup + system-prompt rebuild + history trim
 *   ttft  request sent -> first streamed token (prefill + queueing + network)
 *   gen   first token -> last token (decode / throughput)
 *
 * Time-to-first-token is what a user feels; a one-word reply never leaves the
 * ttft phase, while a long answer is dominated by gen. Read both.
 *
 * Usage:
 *   node scripts/bench/bench-latency.mjs                       # configured model, 3 runs
 *   node scripts/bench/bench-latency.mjs --runs 5
 *   node scripts/bench/bench-latency.mjs --models "openai/gpt-4.1,deepseek/deepseek-v4-flash"
 *   node scripts/bench/bench-latency.mjs --tools               # add a tool-round prompt
 *   node scripts/bench/bench-latency.mjs --prompt "summarise this repo"
 *   node scripts/bench/bench-latency.mjs --json                # machine-readable
 *
 * The first sends (warmup) are discarded so a provider cold start does not
 * poison the numbers. Results are medians unless --json, which keeps the raw
 * per-run samples. No credentials are ever printed.
 */

import { loadConfig } from "../../src/core/config.mjs";
import { readAuth, CopilotClient } from "../../src/core/auth.mjs";
import { CompatibleClient, pickModel, resolveProvider } from "../../src/core/provider.mjs";
import { Agent } from "../../src/core/agent.mjs";

const pnow = () => Number(process.hrtime.bigint()) / 1e6;
const ms = (a, b) => Math.round(b - a);

function parseArgs(argv) {
  const args = { runs: 3, warmup: 1, models: [], tools: false, prompt: null, json: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--runs") args.runs = Math.max(1, Number(argv[++i]) || 3);
    else if (a === "--warmup") args.warmup = Math.max(0, Number(argv[++i]) || 0);
    else if (a === "--models") args.models = String(argv[++i] || "").split(",").map((s) => s.trim()).filter(Boolean);
    else if (a === "--tools") args.tools = true;
    else if (a === "--prompt") args.prompt = String(argv[++i] || "");
    else if (a === "--json") args.json = true;
    else if (a === "-h" || a === "--help") args.help = true;
    else throw new Error(`unknown argument: ${a}`);
  }
  return args;
}

const DEFAULT_PROMPTS = [
  { label: "short", text: "Reply with exactly one word: pong" },
  { label: "medium", text: "In about 120 words, explain what an event loop is." },
];
const TOOL_PROMPT = { label: "tool", text: "List the files in the current working directory." };

function stats(xs) {
  const s = [...xs].filter((n) => Number.isFinite(n)).sort((a, b) => a - b);
  if (!s.length) return null;
  const at = (q) => s[Math.min(s.length - 1, Math.floor(q * (s.length - 1)))];
  return { n: s.length, min: s[0], p50: at(0.5), p95: at(0.95), max: s[s.length - 1] };
}

/** One timed turn. Multi-step turns report null ttft/gen (ambiguous to attribute). */
async function timeTurn(agent, text) {
  const marks = { start: pnow(), firstStart: null, firstDelta: null, end: null, steps: 0 };
  let seen = false;
  await agent.send(text, {
    onMessageStart: () => {
      if (marks.firstStart === null) marks.firstStart = pnow();
      marks.firstDelta = null;
      seen = false;
      marks.steps++;
    },
    onDelta: () => { if (!seen) { marks.firstDelta = pnow(); seen = true; } },
    onMessageEnd: () => { marks.end = pnow(); },
    onToolCall: () => {},
    onToolResult: () => {},
  });
  const done = pnow();
  const single = marks.steps === 1;
  return {
    total: ms(marks.start, done),
    pre: marks.firstStart === null ? null : ms(marks.start, marks.firstStart),
    ttft: single && marks.firstDelta !== null ? ms(marks.firstStart, marks.firstDelta) : null,
    gen: single && marks.firstDelta !== null ? ms(marks.firstDelta, marks.end) : null,
    steps: marks.steps,
    completion: agent.turnUsage?.completion_tokens ?? 0,
  };
}

async function makeClient(config) {
  if (config.apiBase) {
    return new CompatibleClient({
      apiBase: config.apiBase,
      apiKey: config.apiKey,
      model: config.model,
      contextWindow: config.contextWindow,
    });
  }
  const token = process.env.GITHUB_TOKEN || readAuth().github_token;
  if (!token) throw new Error("no saved GitHub token; run the CLI once to log in, or set API_BASE");
  const client = new CopilotClient(token);
  await client.ensureToken();
  return client;
}

function modelList(models, wanted) {
  if (wanted.length) {
    return wanted.map((name) => {
      const hit =
        models.find((m) => m.id === name) ||
        models.find((m) => m.id.includes(name));
      if (!hit) return { requested: name, missing: true };
      return hit;
    });
  }
  return null;
}

async function benchModel({ client, config, model, prompts, runs, warmup }) {
  const local = { ...config, model: model.id };
  let agent = new Agent({ client, config: local });

  for (let i = 0; i < warmup; i++) {
    for (const p of prompts) {
      try { await timeTurn(agent, p.text); } catch { /* warmup failures are retried in the timed pass */ }
    }
  }

  const perPrompt = [];
  for (const p of prompts) {
    agent = new Agent({ client, config: local });
    const samples = [];
    for (let r = 0; r < runs; r++) {
      try {
        samples.push(await timeTurn(agent, p.text));
      } catch (err) {
        samples.push({ error: err.message });
      }
    }
    perPrompt.push({ label: p.label, text: p.text, samples });
  }
  return perPrompt;
}

function flatten(perPrompt) {
  const ok = perPrompt.flatMap((p) => p.samples).filter((s) => !s.error);
  return {
    turns: ok,
    pre: stats(ok.map((s) => s.pre)),
    ttft: stats(ok.map((s) => s.ttft)),
    gen: stats(ok.map((s) => s.gen)),
    total: stats(ok.map((s) => s.total)),
    errors: perPrompt.flatMap((p) => p.samples.filter((s) => s.error).map((s) => s.error)),
  };
}

function tokPerSec(turns) {
  const gen = turns.reduce((a, s) => a + (s.gen || 0), 0);
  const toks = turns.reduce((a, s) => a + (s.completion || 0), 0);
  return gen > 0 && toks > 0 ? Math.round((toks / gen) * 1000) : null;
}

const pad = (v, w) => String(v ?? "-").padEnd(w);
const rpad = (v, w) => String(v ?? "-").padStart(w);
const fmtMs = (s) => (s == null ? "-" : `${s}ms`);

function printReport(report) {
  console.log(`\nprovider: ${report.provider}    models: ${report.models.length}\n`);
  console.log("startup (one-time)");
  console.log(`  config load ${fmtMs(report.setup.configLoadMs)}   auth ${fmtMs(report.setup.authTokenMs)}   list models ${fmtMs(report.setup.listModelsMs)}`);
  console.log("\nper turn (median; p95 in parens)");
  console.log(
    `  ${pad("model", 34)}${pad("prompt", 8)}${rpad("pre", 10)}${rpad("ttft", 12)}${rpad("gen", 10)}${rpad("total", 12)}${rpad("tok/s", 8)}`
  );
  for (const m of report.models) {
    if (m.error) {
      console.log(`  ${pad(m.id, 34)}${"ERROR: " + m.error}`);
      continue;
    }
    for (const p of m.perPrompt) {
      const s = stats(p.samples.filter((x) => !x.error).map((x) => x.total));
      const t = stats(p.samples.filter((x) => !x.error).map((x) => x.ttft));
      const g = stats(p.samples.filter((x) => !x.error).map((x) => x.gen));
      const pre = stats(p.samples.filter((x) => !x.error).map((x) => x.pre));
      const tps = tokPerSec(p.samples.filter((x) => !x.error));
      console.log(
        `  ${pad(m.id, 34)}${pad(p.label, 8)}` +
          `${rpad(fmtMs(pre?.p50) + (pre && pre.p95 !== pre.p50 ? ` (${pre.p95})` : ""), 10)}` +
          `${rpad(fmtMs(t?.p50) + (t && t.p95 !== t.p50 ? ` (${t.p95})` : ""), 12)}` +
          `${rpad(fmtMs(g?.p50), 10)}` +
          `${rpad(fmtMs(s?.p50) + (s && s.p95 !== s.p50 ? ` (${s.p95})` : ""), 12)}` +
          `${rpad(tps ?? "-", 8)}`
      );
    }
    const f = m.flat;
    console.log(
      `  ${pad("", 34)}${pad("all", 8)}` +
        `${rpad(fmtMs(f.pre?.p50), 10)}${rpad(fmtMs(f.ttft?.p50), 12)}` +
        `${rpad(fmtMs(f.gen?.p50), 10)}${rpad(fmtMs(f.total?.p50), 12)}${rpad(tokPerSec(m.flat.turns) ?? "-", 8)}`
    );
    if (f.errors.length) console.log(`  ${pad("", 34)}${f.errors.length} error(s): ${f.errors[0]}`);
  }
  console.log(
    "\n  pre   recall + prompt build + trim\n" +
      "  ttft  request -> first token  (what a user waits for)\n" +
      "  gen   first token -> last token (decode speed, shown as tok/s)\n"
  );
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log("usage: node scripts/bench/bench-latency.mjs [--runs N] [--warmup N] [--models a,b] [--tools] [--prompt \"...\"] [--json]");
    return;
  }

  const t0 = pnow();
  const config = loadConfig();
  config.tools = true;
  const provider = resolveProvider(config.provider);
  if (provider && provider.name !== "copilot" && !config.apiBase) {
    config.apiBase = provider.apiBase;
    if (!config.apiKey && provider.apiKey) config.apiKey = provider.apiKey;
    if (!config.model && provider.defaultModel) config.model = provider.defaultModel;
  }
  const configLoadMs = ms(t0, pnow());

  const tAuth = pnow();
  const client = await makeClient(config);
  const authTokenMs = ms(tAuth, pnow());

  const tModels = pnow();
  const models = await client.models();
  const listModelsMs = ms(tModels, pnow());

  const prompts = args.prompt
    ? [{ label: "custom", text: args.prompt }]
    : args.tools
      ? [...DEFAULT_PROMPTS, TOOL_PROMPT]
      : DEFAULT_PROMPTS;

  let targets;
  const requested = modelList(models, args.models);
  if (requested) {
    targets = requested.map((r) => (r.missing ? { id: r.requested, error: "not in the provider's model list" } : r));
  } else {
    try {
      const picked = pickModel(models, config.model, true);
      targets = [{ ...picked, id: picked.id }];
    } catch (err) {
      targets = [{ id: config.model || "?", error: err.message }];
    }
  }

  const results = [];
  for (const target of targets) {
    if (target.error) {
      results.push({ id: target.id, error: target.error });
      continue;
    }
    if (target.tools === false) {
      results.push({ id: target.id, error: "does not support tool calls; benchmarks run with tools on" });
      continue;
    }
    const perPrompt = await benchModel({ client, config, model: target, prompts, runs: args.runs, warmup: args.warmup });
    results.push({ id: target.id, perPrompt, flat: flatten(perPrompt) });
  }

  const report = {
    provider: config.apiBase || "copilot",
    setup: { configLoadMs, authTokenMs, listModelsMs },
    runs: args.runs,
    warmup: args.warmup,
    models: results,
  };

  if (args.json) console.log(JSON.stringify(report, null, 2));
  else printReport(report);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
