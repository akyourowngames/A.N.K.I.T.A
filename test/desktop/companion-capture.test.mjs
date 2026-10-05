import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { MAX_TEXT_BYTES, ROUTES } from '../../desktop/browser-helper/protocol.mjs';

const module = await import('../../desktop/electron/companion-capture.mjs').catch(() => null);
const origin = 'chrome-extension://' + 'a'.repeat(32);
async function fixture(t) {
  assert.ok(module, 'authenticated companion capture bridge is implemented');
  const dir = await mkdtemp(join(tmpdir(), 'ankita-capture-test-'));
  const received = [], threads = new Set(['chief', 'research']);
  let now = Date.now();
  const options = { configFile: join(dir, 'bridge.json'), threadExists: id => threads.has(id), onCapture: item => received.push(item), now: () => now };
  const bridge = new module.CompanionCapture(options);
  await bridge.start();
  t.after(async () => { await bridge.close(); await rm(dir, { recursive: true, force: true }); });
  const setup = bridge.setup();
  const post = async (route, body, token) => {
    const response = await fetch(setup.address + route, { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: JSON.stringify(body) });
    return { status: response.status, body: await response.json() };
  };
  const pairing = await post('/pair', { code: setup.code });
  assert.equal(pairing.status, 200);
  return { bridge, post, received, threads, options, token: pairing.body.token, advance: ms => { now += ms; } };
}
test('paired real HTTP capture belongs to the original agent and is consumed once', async t => {
  const f = await fixture(t), ticketId = randomUUID();
  const ticket = f.bridge.register({ ticketId, threadId: 'research', surface: 'island', sourceId: 'window' });
  const payload = { ...ticket, title: 'Rendered fixture', url: 'https://example.test/page', text: 'The rendered page contains a private research note.' };
  assert.equal((await f.post('/capture', payload)).status, 401);
  assert.equal((await f.post('/capture', payload, f.token)).status, 200);
  assert.equal(f.received.length, 1);
  assert.equal(f.received[0].threadId, 'research');
  assert.match(Buffer.from(f.received[0].attachment.data, 'base64').toString(), /private research note/);
  assert.equal((await f.post('/capture', payload, f.token)).status, 409);
  assert.equal(f.bridge.inbox('main').length, 0);
  assert.equal(f.bridge.inbox('island').length, 1);
  f.bridge.ack(f.received[0].id, 'island');
  assert.equal(f.bridge.inbox('island').length, 0);
});
test('cancelled, stale, forged, wrong-instance and deleted-recipient drops cannot mutate drafts', async t => {
  const f = await fixture(t);
  const send = ticket => f.post('/capture', { ...ticket, url: 'https://example.test/', title: 'Page', text: 'Readable page' }, f.token);
  const cancelled = f.bridge.register({ ticketId: randomUUID(), threadId: 'chief', surface: 'main', sourceId: 'one' });
  f.bridge.cancel(cancelled.ticketId, 'other');
  assert.equal((await send({ ...cancelled, instanceId: 'forged' })).status, 409);
  f.bridge.cancel(cancelled.ticketId, 'one');
  assert.equal((await send(cancelled)).status, 409);
  const expired = f.bridge.register({ ticketId: randomUUID(), threadId: 'chief', surface: 'main', sourceId: 'one' });
  f.advance(module.TICKET_TTL_MS + 1);
  assert.equal((await send(expired)).status, 410);
  const deleted = f.bridge.register({ ticketId: randomUUID(), threadId: 'research', surface: 'main', sourceId: 'one' });
  f.threads.delete('research');
  assert.equal((await send(deleted)).status, 410);
  assert.equal((await send({ ticketId: randomUUID(), instanceId: f.bridge.instanceId })).status, 409);
  assert.equal(f.received.length, 0);
});
test('pairing survives restart while previous instance tickets do not', async t => {
  const f = await fixture(t), address = f.bridge.setup().address;
  const ticket = f.bridge.register({ ticketId: randomUUID(), threadId: 'chief', surface: 'main', sourceId: 'one' });
  await f.bridge.close();
  const restart = new module.CompanionCapture(f.options);
  await restart.start();
  t.after(() => restart.close());
  assert.equal(restart.setup().address, address);
  assert.equal(restart.setup().paired, 1);
  const result = await f.post('/capture', { ...ticket, url: 'https://example.test', text: 'Old drop' }, f.token);
  assert.equal(result.status, 409);
});
test('wrong website origin, forged credentials and oversized or unreadable pages leave tickets unconsumed', async t => {
  const f = await fixture(t);
  const ticket = f.bridge.register({ticketId:randomUUID(),threadId:'chief',surface:'main',sourceId:'one'});
  const payload = {...ticket,url:'https://example.test/page',title:'Bounded page',text:'A readable page'};
  const website = await fetch(f.bridge.setup().address + ROUTES.capture,{method:'POST',headers:{Origin:'https://example.test','Content-Type':'application/json',Authorization:'Bearer '+f.token},body:JSON.stringify(payload)});
  assert.equal(website.status,403);
  assert.equal((await f.post(ROUTES.capture,payload,'forged')).status,401);
  assert.equal((await f.post(ROUTES.capture,{...payload,text:'x'.repeat(MAX_TEXT_BYTES+1)},f.token)).status,413);
  assert.equal((await f.post(ROUTES.capture,{...payload,url:'file:///private.txt'},f.token)).status,400);
  assert.equal((await f.post(ROUTES.capture,{...payload,text:''},f.token)).status,400);
  assert.equal(f.received.length,0);
  assert.equal((await f.post(ROUTES.capture,payload,f.token)).status,200);
});
test('concurrent recipients retain independent identity and pairing codes cannot be reused', async t => {
  const f = await fixture(t), setup = f.bridge.setup();
  const pair = await f.post(ROUTES.pair,{code:setup.code});
  assert.equal(pair.status,200);
  assert.equal((await f.post(ROUTES.pair,{code:setup.code})).status,403);
  const tickets = ['chief','research'].map(threadId=>f.bridge.register({ticketId:randomUUID(),threadId,surface:'island',sourceId:'one'}));
  const results = await Promise.all(tickets.map((ticket,index)=>f.post(ROUTES.capture,{...ticket,url:'https://example.test/'+index,text:'Page '+index},pair.body.token)));
  assert.deepEqual(results.map(result=>result.status),[200,200]);
  assert.deepEqual(f.received.map(item=>item.threadId).sort(),['chief','research']);
});
test('Chrome and Edge helpers with the same extension origin keep independent pairing credentials', async t => {
  const f = await fixture(t), setup = f.bridge.setup();
  const second = await f.post(ROUTES.pair,{code:setup.code,helperId:randomUUID()});
  assert.equal(second.status,200);
  const ticket = f.bridge.register({ticketId:randomUUID(),threadId:'chief',surface:'main',sourceId:'one'});
  const payload = {...ticket,url:'https://example.test/original-browser',text:'The first browser remains paired'};
  assert.equal((await f.post(ROUTES.capture,payload,f.token)).status,200);
  assert.equal(f.bridge.setup().paired,2);
});
test('development origin-only credentials migrate without losing the existing browser pairing', async t => {
  const f = await fixture(t), port = new URL(f.bridge.setup().address).port;
  await f.bridge.close();
  await writeFile(f.options.configFile,JSON.stringify({port:Number(port),helpers:{[origin]:f.token}}));
  const migrated = new module.CompanionCapture(f.options);
  await migrated.start();t.after(()=>migrated.close());
  const ticket = migrated.register({ticketId:randomUUID(),threadId:'chief',surface:'main',sourceId:'one'});
  assert.equal((await f.post(ROUTES.capture,{...ticket,url:'https://example.test/migration',text:'Existing pairing still works'},f.token)).status,200);
  assert.equal(migrated.setup().paired,1);
  const saved=JSON.parse(await readFile(f.options.configFile,'utf8'));
  assert.equal(Object.keys(saved.helpers).includes(origin),false);
});
test('a remembered-port conflict does not silently start a different bridge', async t => {
  const f=await fixture(t),address=f.bridge.setup().address;
  const conflict=new module.CompanionCapture(f.options);
  await assert.rejects(conflict.start(),error=>error.code==='EADDRINUSE');
  assert.equal(f.bridge.setup().address,address);
  await conflict.close();
});
