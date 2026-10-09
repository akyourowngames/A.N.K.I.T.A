import { test } from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  FLAGS, SLASH_GROUPS, BANNER_HINT, COMPOSIO_ACTIONS,
  commandNames, itemFor, subcommandHint, unknownActionMessage, closestCommand,
} from "../../src/core/commands.mjs";
import { JOB_COMMANDS } from "../../src/tooling/job-ui.mjs";
import { helpText, banner, setColorEnabled } from "../../src/core/ui.mjs";
import { makeCompleter } from "../../src/core/cli.mjs";
import * as composioTool from "../../tools/connectors/composio.mjs";

const ROOT = path.resolve(fileURLToPath(import.meta.url), "..", "..", "..");
const CHAT = path.join(ROOT, "chat.mjs");
const runHelp = promisify(execFile);

test("--help prints every flag from the registry", async () => {
  const { stdout } = await runHelp(process.execPath, [CHAT, "--help"], {
    env: { ...process.env, NO_COLOR: "1" },
  });
  for (const f of FLAGS) {
    const long = stdout.includes(f.long);
    assert.ok(long, `--help missing ${f.long}`);
    if (f.short) assert.ok(stdout.includes(f.short), `--help missing ${f.short}`);
    assert.ok(stdout.includes(f.desc), `--help missing description for ${f.long}`);
  }
});

test("helpText covers every registered command and job command", () => {
  setColorEnabled(false);
  try {
    const text = helpText({ agentName: "ankita" });
    for (const name of commandNames()) assert.ok(text.includes(name), `help missing ${name}`);
    for (const job of JOB_COMMANDS) assert.ok(text.includes(job), `help missing ${job}`);
    for (const name of ["/mcp", "/composio", "/daemon", "/quit"]) assert.ok(text.includes(name), `help missing ${name}`);
  } finally {
    setColorEnabled(Boolean(process.stdout.isTTY));
  }
});

test("no slash command in helpText is absent from the registry", () => {
  setColorEnabled(false);
  try {
    const text = helpText({ agentName: "ankita" });
    const known = new Set(commandNames());
    for (const m of text.matchAll(/(^|\s)\/([a-z][a-z-]*)/g)) {
      assert.ok(known.has(`/${m[2]}`), `help shows /${m[2]} which is not registered`);
    }
  } finally {
    setColorEnabled(Boolean(process.stdout.isTTY));
  }
});

test("registry commands all have descriptions and grouped titles", () => {
  for (const group of SLASH_GROUPS) {
    assert.ok(group.title.length && group.items.length);
    for (const item of group.items) assert.ok(item.desc, `${item.name} has no description`);
  }
});

test("COMPOSIO_ACTIONS includes every action composio.mjs handles", async () => {
  for (const action of ["status", "list", "search", "accounts", "connect", "disconnect", "reload", "tiers", "allow", "deny"]) {
    assert.ok(COMPOSIO_ACTIONS.includes(action), `registry missing composio action ${action}`);
  }
  const result = await composioTool.run(
    { action: "bogus" },
    { config: {}, composioStore: {} },
  );
  assert.match(result, /unknown Composio action "bogus"/);
  for (const action of COMPOSIO_ACTIONS) assert.ok(result.includes(action), `error does not list ${action}`);
});

test("makeCompleter completes commands and subcommands from the registry", () => {
  const completer = makeCompleter([{ id: "claude-sonnet-5" }]);
  assert.deepEqual(completer("/mc")[0], ["/mcp"]);
  assert.deepEqual(completer("/comma")[0], ["/commands"]);
  const composio = completer("/composio ")[0];
  for (const action of ["tiers", "allow", "always", "deny"]) {
    assert.ok(composio.includes(`/composio ${action}`), `no completion for ${action}`);
  }
  assert.ok(completer("/browser e")[0].includes("/browser enable isolated"));
  assert.ok(completer("/mcp re")[0].includes("/mcp reload"));
  assert.deepEqual(completer("/model cl")[0], ["/model claude-sonnet-5"]);
});

test("usage hints list the valid subcommands", () => {
  assert.equal(subcommandHint("/mcp"), `try: ${itemFor("/mcp").actions.join(", ")}`);
  assert.match(unknownActionMessage("/mcp", "foo"), /try: list, add, remove, enable, disable, reload/);
  assert.match(unknownActionMessage("/composio", "foo"), /tiers/);
});

test("closestCommand suggests fixes for typos", () => {
  assert.equal(closestCommand("/hepl"), "/help");
  assert.equal(closestCommand("/compo"), "/composio");
  assert.equal(closestCommand("/broswer"), "/browser");
  assert.equal(closestCommand("/zzzzz"), null);
});

test("banner prints version, provider and the discoverability hint", () => {
  setColorEnabled(false);
  const original = process.stdout.write.bind(process.stdout);
  let captured = "";
  try {
    process.stdout.write = (chunk) => {
      captured += String(chunk);
      return true;
    };
    banner({
      agentName: "ankita", username: "tester", model: "m", version: "9.9.9",
      provider: "groq", tools: true, autoApprove: false, cwd: "C:\\", count: 3,
    });
  } finally {
    process.stdout.write = original;
    setColorEnabled(Boolean(process.stdout.isTTY));
  }
  assert.match(captured, /version    9\.9\.9/);
  assert.match(captured, /provider   groq/);
  assert.ok(captured.includes(BANNER_HINT));
});

test("banner can hide the hint (daemon) and survives missing version/provider", () => {
  setColorEnabled(false);
  const original = process.stdout.write.bind(process.stdout);
  let captured = "";
  try {
    process.stdout.write = (chunk) => {
      captured += String(chunk);
      return true;
    };
    banner({ agentName: "ankita", username: "u", model: "m", tools: false, autoApprove: false, cwd: "C:\\", hint: false });
  } finally {
    process.stdout.write = original;
    setColorEnabled(Boolean(process.stdout.isTTY));
  }
  assert.ok(!captured.includes(BANNER_HINT));
  assert.ok(!captured.includes("version"));
});
