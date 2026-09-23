import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

let tool;
try { tool = await import("../tools/http-request.mjs"); } catch (err) { if (err.code !== "ERR_MODULE_NOT_FOUND") throw err; }

async function server(t, handler) {
  const instance = http.createServer(handler);
  await new Promise(resolve => instance.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => { instance.close(resolve); instance.closeAllConnections(); }));
  return `http://127.0.0.1:${instance.address().port}`;
}

test("HTTP tool exposes method-sensitive approval and secret-safe display", () => {
  assert.ok(tool, "http_request implementation is available");
  assert.equal(tool.name, "http_request");
  assert.equal(tool.readOnly({}), true);
  assert.equal(tool.needsApproval({ method: "head" }), false);
  for (const method of ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]) assert.equal(tool.needsApproval({ method }), true);
  const shown = JSON.stringify(tool.display({ url: "https://example.com/?api_key=secretquery&safe=value", headers: { Authorization: "secretbearer", "X-API-Key": "secretkey" }, auth: { type: "basic", username: "user", password: "secretpassword" }, json: { token: "secretbody" } }));
  for (const secret of ["secretquery", "secretbearer", "secretkey", "secretpassword", "secretbody"]) assert.ok(!shown.includes(secret), shown);
});

test("approval distinguishes operations while redacting nested and repeated secrets", () => {
  const common = { method: "POST", url: "https://example.com/actions?mode=preview&token=query-secret", auth: { type: "bearer", token: "bearer-secret" }, headers: { "X-Access-Code": "header-secret" } };
  const preview = tool.approval({ ...common, json: { action: "preview", nested: [{ password: "nested-secret", label: "bearer-secret" }], note: "header-secret" } });
  const deletion = tool.approval({ ...common, url: common.url.replace("mode=preview", "mode=delete_all"), json: { action: "delete_all", confirm: true } });
  assert.match(preview, /mode=preview/);
  assert.match(preview, /"action": "preview"/);
  assert.match(deletion, /mode=delete_all/);
  assert.match(deletion, /"action": "delete_all"/);
  for (const secret of ["query-secret", "bearer-secret", "header-secret", "nested-secret"]) assert.ok(!preview.includes(secret), preview);
  const form = tool.approval({ ...common, form: { action: "delete_all", client_secret: "form-secret", nested: { access_code: "access-secret", count: 7 } } });
  assert.match(form, /delete_all/);
  assert.match(form, /"count": 7/);
  assert.ok(!form.includes("form-secret"));
  assert.ok(!form.includes("access-secret"));
  const trace = JSON.stringify(tool.display({ ...common, json: { action: "delete_all" } }));
  assert.ok(!trace.includes("delete_all"));
  assert.ok(!trace.includes("mode=preview"));
});

test("raw approval preview reports byte size and truncation without exposing known credentials", () => {
  const body = `action=delete_all token=raw-secret ${"é".repeat(5000)}`;
  const shown = tool.approval({ url: "http://localhost/actions", method: "POST", body, auth: { type: "bearer", token: "raw-secret" } });
  assert.match(shown, /action=delete_all/);
  assert.ok(!shown.includes("raw-secret"));
  assert.match(shown, new RegExp(`"bytes": ${Buffer.byteLength(body)}`));
  assert.match(shown, /"truncated": true/);
  assert.ok(shown.length < 6000);
});

test("POST sends JSON, raw and form bodies and bearer/basic authentication", async t => {
  const url = await server(t, async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({ method: req.method, headers: req.headers, body }));
  });
  let result = JSON.parse(await tool.run({ url, method: "POST", json: { greeting: "hello" }, auth: { type: "bearer", token: "token-value" } }));
  let echo = JSON.parse(result.body);
  assert.equal(echo.method, "POST");
  assert.equal(echo.body, '{"greeting":"hello"}');
  assert.equal(echo.headers.authorization, "Bearer token-value");
  assert.match(echo.headers["content-type"], /application\/json/);
  result = JSON.parse(await tool.run({ url, method: "POST", form: { name: "a b", tags: ["x", "y"] }, auth: { type: "basic", username: "user", password: "pass" } }));
  echo = JSON.parse(result.body);
  assert.equal(echo.body, "name=a+b&tags=x&tags=y");
  assert.equal(echo.headers.authorization, `Basic ${Buffer.from("user:pass").toString("base64")}`);
  result = JSON.parse(await tool.run({ url, method: "PATCH", body: "raw payload", headers: { "x-custom": "yes" } }));
  assert.equal(JSON.parse(result.body).body, "raw payload");
});

test("HTTP error responses preserve headers and body with expected status control", async t => {
  const url = await server(t, (_req, res) => { res.writeHead(422, { "x-result": "validation", "content-type": "application/json", "set-cookie": "session=response-cookie; HttpOnly" }); res.end('{"error":"invalid"}'); });
  const result = JSON.parse(await tool.run({ url, expected_status: [200, 201] }));
  assert.equal(result.status, 422);
  assert.equal(result.headers["x-result"], "validation");
  assert.equal(result.headers["set-cookie"], "session=response-cookie; HttpOnly");
  assert.equal(result.body, '{"error":"invalid"}');
  assert.equal(result.expected_status_matched, false);
  const accepted = JSON.parse(await tool.run({ url, expected_status: 422 }));
  assert.equal(accepted.expected_status_matched, true);
});

test("redirect policies preserve manual response and strip credentials cross-origin", async t => {
  let received;
  const target = await server(t, (req, res) => { received = req.headers; res.end("arrived"); });
  const source = await server(t, (_req, res) => { res.writeHead(302, { location: `${target}/next` }); res.end("redirect body"); });
  const manual = JSON.parse(await tool.run({ url: source, redirect: "manual" }));
  assert.equal(manual.status, 302);
  assert.equal(manual.body, "redirect body");
  await assert.rejects(tool.run({ url: source, redirect: "error" }), /redirect/i);
  const followed = JSON.parse(await tool.run({ url: source, headers: { authorization: "Bearer secret", cookie: "session=secret", "x-api-key": "secret", "x-auth": "secret", "subscription-key": "secret", "x-access-code": "secret", "x-public": "public", "accept-language": "en" } }));
  assert.equal(followed.body, "arrived");
  assert.equal(received.authorization, undefined);
  assert.equal(received.cookie, undefined);
  assert.equal(received["x-api-key"], undefined);
  assert.equal(received["x-auth"], undefined);
  assert.equal(received["subscription-key"], undefined);
  assert.equal(received["x-access-code"], undefined);
  assert.equal(received["x-public"], undefined);
  assert.equal(received["accept-language"], "en");
  await assert.rejects(tool.run({ url: source, max_redirects: 0 }), /redirect/i);
});

test("redirects never replay a mutation automatically", async t => {
  let mutations = 0;
  const target = await server(t, (_req, res) => { mutations++; res.end("mutated"); });
  const source = await server(t, (_req, res) => { res.writeHead(307, { location: target }); res.end(); });
  await assert.rejects(tool.run({ url: source, method: "POST", body: "one" }), /redirect.*mutat|mutat.*redirect/i);
  assert.equal(mutations, 0);
});

test("binary responses use bounded base64 and text truncation counts bytes", async t => {
  const url = await server(t, (req, res) => {
    if (req.url === "/binary") { res.setHeader("content-type", "application/octet-stream"); res.end(Buffer.from([0, 255, 128, 1, 2])); }
    else { res.setHeader("content-type", "text/plain"); res.end("abcdefghij"); }
  });
  const binary = JSON.parse(await tool.run({ url: `${url}/binary`, max_bytes: 3 }));
  assert.equal(binary.encoding, "base64");
  assert.deepEqual(Buffer.from(binary.body, "base64"), Buffer.from([0, 255, 128]));
  assert.equal(binary.truncated, true);
  const text = JSON.parse(await tool.run({ url, max_bytes: 4 }));
  assert.equal(text.body, "abcd");
  assert.equal(text.truncated, true);
});

test("timeout includes streaming body and caller cancellation interrupts it", async t => {
  const url = await server(t, (_req, res) => { res.writeHead(200, { "content-type": "text/plain" }); res.write("started"); });
  await assert.rejects(tool.run({ url, timeout_ms: 50 }), /timeout/i);
  const controller = new AbortController();
  const pending = tool.run({ url, timeout_ms: 5000 }, { signal: controller.signal });
  setTimeout(() => controller.abort(new Error("secret abort reason")), 30);
  await assert.rejects(pending, err => /abort/i.test(err.message) && !err.message.includes("secret"));
});

test("validation and failures do not expose outbound credentials", async () => {
  for (const args of [
    { url: "https://user:secret@example.com" },
    { url: "file:///secret" },
    { url: "not-a-url?token=secret" },
    { url: "http://127.0.0.1:1/?token=secret", headers: { Authorization: "Bearer secret" } },
    { url: "https://example.com", method: "GET", body: "secret" },
    { url: "https://example.com", method: "POST", body: "secret", json: {} },
  ]) await assert.rejects(tool.run(args), err => !err.message.includes("secret"));
});

test("HEAD has no body and same-origin redirects retain authorization", async t => {
  let authorization;
  const url = await server(t, (req, res) => {
    if (req.url === "/redirect") { res.writeHead(302, { location: "/target" }); res.end(); }
    else { authorization = req.headers.authorization; res.end("response"); }
  });
  const head = JSON.parse(await tool.run({ url, method: "HEAD" }));
  assert.equal(head.body, "");
  const followed = JSON.parse(await tool.run({ url: `${url}/redirect`, auth: { type: "bearer", token: "same-origin" } }));
  assert.equal(followed.body, "response");
  assert.equal(authorization, "Bearer same-origin");
});

test("303 after POST follows as a bodyless GET without replaying the mutation", async t => {
  let posts = 0;
  let redirected;
  const url = await server(t, async (req, res) => {
    if (req.url === "/post") { posts++; res.writeHead(303, { location: "/result" }); res.end(); }
    else { let body = ""; for await (const chunk of req) body += chunk; redirected = { method: req.method, body, type: req.headers["content-type"] }; res.end("done"); }
  });
  const result = JSON.parse(await tool.run({ url: `${url}/post`, method: "POST", json: { message: "create" } }));
  assert.equal(posts, 1);
  assert.deepEqual(redirected, { method: "GET", body: "", type: undefined });
  assert.equal(result.body, "done");
});

test("pre-aborted caller signal prevents the request", async t => {
  let calls = 0;
  const url = await server(t, (_req, res) => { calls++; res.end(); });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(tool.run({ url }, { signal: controller.signal }), /aborted/);
  assert.equal(calls, 0);
});
