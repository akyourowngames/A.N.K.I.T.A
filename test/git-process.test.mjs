import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { once } from "node:events";

async function tool(file) {
  const value = await import(`../tools/${file}.mjs`).catch(() => null);
  assert.ok(value, `${file} tool must exist`);
  return value;
}

async function repo(t) {
  const cwd = await fs.mkdtemp(path.join(os.tmpdir(), "ankita-git-"));
  t.after(() => fs.rm(cwd, { recursive: true, force: true }));
  const git = (...args) => execFileSync("git", args, { cwd, windowsHide: true, encoding: "utf8" });
  git("init", "-b", "main");
  // The fixture asserts exact LF bytes after restore. CI runners may inherit
  // core.autocrlf=true, which would rewrite the checkout to CRLF.
  git("config", "core.autocrlf", "false");
  git("config", "user.name", "Tool Test");
  git("config", "user.email", "tool@example.invalid");
  await fs.writeFile(path.join(cwd, "hello.txt"), "first\n");
  git("add", "--", "hello.txt");
  git("commit", "-m", "initial");
  return { cwd, git };
}

test("git distinguishes read actions and mutation subcommands", async () => {
  const git = await tool("git");
  for (const args of [{ action: "status" }, { action: "diff" }, { action: "log" }, { action: "show" }, { action: "blame", paths: ["a"] }, { action: "branch" }, { action: "stash", operation: "list" }]) {
    assert.equal(git.needsApproval(args), false);
    assert.equal(git.readOnly(args), true);
  }
  for (const args of [{ action: "checkout", ref: "main" }, { action: "commit", message: "m" }, { action: "restore", paths: ["a"] }, { action: "stage", paths: ["a"] }, { action: "unstage", paths: ["a"] }, { action: "branch", operation: "create", branch: "new" }, { action: "branch", operation: "delete", branch: "new" }, { action: "stash", operation: "push" }, { action: "stash", operation: "pop" }, { action: "stash", operation: "apply" }, { action: "stash", operation: "drop" }]) {
    assert.equal(git.needsApproval(args), true);
    assert.equal(git.readOnly(args), false);
    assert.match(await git.approval(args, { cwd: "/tmp" }), /git/);
  }
});

test("git safely stages literal paths, unstages, commits, restores and reads history", async (t) => {
  const toolGit = await tool("git");
  const { cwd, git } = await repo(t);
  const ctx = { cwd };
  const run = (args) => toolGit.run(args, ctx);
  await fs.writeFile(path.join(cwd, "hello.txt"), "second\n");
  await fs.writeFile(path.join(cwd, "-odd.txt"), "literal\n");
  assert.match(await run({ action: "status" }), /hello\.txt/);
  assert.match(await run({ action: "diff" }), /second/);
  assert.match(await run({ action: "stage", paths: ["-odd.txt"] }), /exit code: 0/);
  assert.equal(git("diff", "--cached", "--name-only").trim(), "-odd.txt");
  await run({ action: "unstage", paths: ["-odd.txt"] });
  assert.equal(git("diff", "--cached", "--name-only").trim(), "");
  await run({ action: "stage", paths: ["hello.txt"] });
  await run({ action: "commit", message: "second commit" });
  assert.equal(git("log", "-1", "--format=%s").trim(), "second commit");
  await fs.writeFile(path.join(cwd, "hello.txt"), "discard\n");
  await run({ action: "restore", paths: ["hello.txt"] });
  assert.equal(await fs.readFile(path.join(cwd, "hello.txt"), "utf8"), "second\n");
  assert.match(await run({ action: "log", limit: 1 }), /second commit/);
  assert.match(await run({ action: "show", ref: "HEAD:hello.txt" }), /second/);
  assert.match(await run({ action: "blame", paths: ["hello.txt"] }), /second/);
  await run({ action: "branch", operation: "create", branch: "feature" });
  await run({ action: "checkout", ref: "feature" });
  assert.equal(git("branch", "--show-current").trim(), "feature");
  await run({ action: "checkout", ref: "main" });
  await run({ action: "branch", operation: "delete", branch: "feature" });
  assert.doesNotMatch(git("branch"), /feature/);
});

test("git stash mutations and rejected options cannot smuggle commands", async (t) => {
  const toolGit = await tool("git");
  const { cwd, git } = await repo(t);
  await fs.writeFile(path.join(cwd, "hello.txt"), "stashed\n");
  await toolGit.run({ action: "stash", operation: "push", message: "safe stash" }, { cwd });
  assert.match(await toolGit.run({ action: "stash", operation: "list" }, { cwd }), /safe stash/);
  await toolGit.run({ action: "stash", operation: "apply" }, { cwd });
  assert.equal(await fs.readFile(path.join(cwd, "hello.txt"), "utf8"), "stashed\n");
  await toolGit.run({ action: "stash", operation: "drop" }, { cwd });
  assert.equal(git("stash", "list").trim(), "");
  for (const args of [{ action: "checkout", ref: "--orphan=bad" }, { action: "show", ref: "--output=bad" }, { action: "branch", operation: "create", branch: "-bad" }, { action: "restore" }, { action: "stash", operation: "clear" }]) {
    await assert.rejects(async () => toolGit.run(args, { cwd }), /invalid|required|unsupported|must/i);
  }
});

test("git can unstage files before the first commit without deleting the working copy", async (t) => {
  const toolGit = await tool("git");
  const cwd = await fs.mkdtemp(path.join(os.tmpdir(), "ankita-unborn-"));
  t.after(() => fs.rm(cwd, { recursive: true, force: true }));
  execFileSync("git", ["init", "-b", "main"], { cwd, windowsHide: true });
  await fs.writeFile(path.join(cwd, "first.txt"), "keep me\n");
  await toolGit.run({ action: "stage", paths: ["first.txt"] }, { cwd });
  assert.match(await toolGit.run({ action: "unstage", paths: ["first.txt"] }, { cwd }), /exit code: 0/);
  assert.equal(execFileSync("git", ["ls-files"], { cwd, windowsHide: true, encoding: "utf8" }).trim(), "");
  assert.equal(await fs.readFile(path.join(cwd, "first.txt"), "utf8"), "keep me\n");
});

test("read-only git actions do not execute configured fsmonitor or textconv helpers", async (t) => {
  const toolGit = await tool("git");
  const { cwd, git } = await repo(t);
  const monitorMarker = path.join(cwd, "monitor-ran");
  const textconvMarker = path.join(cwd, "textconv-ran");
  await fs.writeFile(path.join(cwd, "monitor.cjs"), `require('node:fs').writeFileSync(${JSON.stringify(monitorMarker)}, 'yes');\n`);
  await fs.writeFile(path.join(cwd, "textconv.cjs"), `require('node:fs').writeFileSync(${JSON.stringify(textconvMarker)}, 'yes');\n`);
  await fs.writeFile(path.join(cwd, ".gitattributes"), "hello.txt diff=custom\n");
  git("config", "core.fsmonitor", "node monitor.cjs");
  git("config", "diff.custom.textconv", "node textconv.cjs");
  await fs.writeFile(path.join(cwd, "hello.txt"), "changed\n");
  const ctx = { cwd };
  for (const action of [{ action: "status" }, { action: "diff" }, { action: "show" }, { action: "blame", paths: ["hello.txt"] }]) {
    await toolGit.run(action, ctx);
  }
  await assert.rejects(fs.access(monitorMarker), { code: "ENOENT" });
  await assert.rejects(fs.access(textconvMarker), { code: "ENOENT" });
});

async function server(t, requestedPort = 0) {
  const child = spawn(process.execPath, ["-e", `require('node:net').createServer().listen(${requestedPort},'127.0.0.1',function(){console.log(this.address().port)})`], { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  t.after(() => { if (child.exitCode === null) child.kill(); });
  const [data] = await once(child.stdout, "data");
  return { child, port: Number(String(data).trim()) };
}

test("port status finds real listener and kill requires an approved snapshot", async (t) => {
  const status = await tool("port-status");
  const kill = await tool("kill-process");
  const { child, port } = await server(t);
  assert.match(await status.run({ port }), new RegExp(String(child.pid)));
  assert.equal(status.needsApproval, false);
  const args = { port, force: true };
  const ctx = {};
  await assert.rejects(async () => kill.run(args, ctx), /approval|snapshot|preview/i);
  const preview = await kill.approval(args, ctx);
  assert.match(preview, new RegExp(String(child.pid)));
  assert.match(preview, /taskkill|kill/);
  const closed = once(child, "close");
  assert.match(await kill.run(args, ctx), /terminated|killed|exit code: 0|Sent SIG/i);
  await closed;
  assert.match(await status.run({ port }), /no .*listener|no .*process|not .*use/i);
});

test("kill rejects own process, invalid ids, mismatched previews and reused previews", async (t) => {
  const kill = await tool("kill-process");
  for (const args of [{ pid: process.pid }, { pid: 0 }, { pid: 1 }, { pid: -2 }, { port: 0 }, { pid: 123, port: 123 }]) {
    await assert.rejects(async () => kill.approval(args, {}), /refus|invalid|must|exactly/i);
  }
  const { child } = await server(t);
  const ctx = {};
  const args = { pid: child.pid, force: true };
  await kill.approval(args, ctx);
  await assert.rejects(async () => kill.run({ ...args, force: false }, ctx), /approval|snapshot|preview/i);
  const closed = once(child, "close");
  await kill.run(args, ctx);
  await closed;
  await assert.rejects(async () => kill.run(args, ctx), /approval|snapshot|preview/i);
});

test("kill refuses a new owner on an approved port", async (t) => {
  const kill = await tool("kill-process");
  const { child, port } = await server(t);
  const args = { port, force: true };
  const ctx = {};
  await kill.approval(args, ctx);
  const closed = once(child, "close");
  child.kill();
  await closed;
  const replacement = await server(t, port);
  await assert.rejects(async () => kill.run(args, ctx), /changed since approval/i);
  assert.equal(replacement.child.exitCode, null);
});

test("socket parsers distinguish local listeners, remote ports and hidden owners", async () => {
  const { parseNetstat, parseLsof, parseSs } = await tool("_process");
  assert.deepEqual(parseNetstat("TCP 127.0.0.1:4321 0.0.0.0:0 LISTENING 99\nTCP 127.0.0.1:1000 10.0.0.1:4321 ESTABLISHED 44\nUDP [::]:4321 *:* 77", 4321).map((x) => x.pid), [99, 77]);
  assert.deepEqual(parseLsof("p99\ncnode\nf1\nn127.0.0.1:4321\nTST=LISTEN\nf2\nn127.0.0.1:4321->127.0.0.1:33\nTST=ESTABLISHED\np77\ncudp\nf3\nn*:4321\n", 4321).map((x) => x.pid), [99, 77]);
  assert.deepEqual(parseSs('tcp LISTEN 0 128 127.0.0.1:4321 0.0.0.0:* users:(("node",pid=99,fd=3))\nudp UNCONN 0 0 [::]:4321 [::]:*', 4321).map((x) => x.pid), [99, null]);
});

test("command execution bounds output and responds to timeout and cancellation", async () => {
  const { execute } = await tool("_process");
  const result = await execute(process.execPath, ["-e", "process.stdout.write('x'.repeat(100000))"], { max_output_bytes: 1024 });
  assert.equal(result.code, 0);
  assert.equal(result.truncated, true);
  assert.ok(Buffer.byteLength(result.output) <= 1024);
  assert.match(result.output, /truncated/);
  await assert.rejects(execute(process.execPath, ["-e", "setInterval(()=>{},1000)"], { timeout_ms: 100 }), /timed out/i);
  const ctrl = new AbortController();
  const pending = execute(process.execPath, ["-e", "setInterval(()=>{},1000)"], { signal: ctrl.signal });
  ctrl.abort();
  await assert.rejects(pending, /cancelled/i);
  await assert.rejects(execute(process.execPath, ["-e", "process.exit(0)"], { signal: ctrl.signal }), /cancelled/i);
});
