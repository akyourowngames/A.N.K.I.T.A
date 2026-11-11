import {
  PHONE_ROUTES, PHONE_PAIRING_PROTOCOL_VERSION, PHONE_SESSION_KEY, PHONE_POLL_MS, PHONE_REQUEST_TIMEOUT_MS,
  MAX_DEVICE_NAME_CHARS, MAX_PROMPT_CHARS, PHONE_CONTEXT_TITLE_CHARS, PHONE_CONTEXT_TEXT_CHARS, FINGERPRINT_PATTERN,
} from './contract.mjs';

const $ = id => document.getElementById(id);
const TERMINAL = new Set(['completed', 'cancelled', 'failed']); // Existing phone run contract, independent of saved-task states.
const PLATFORM = 'browser'; // Desktop displays this distinct from a native companion.
let token = '', pending = null, preview = null, selectedTask = null, currentRun = null, currentApproval = null;
let pairingTimer, runTimer, pairingBusy = false, sending = false;
let connectionEpoch = 0; // Invalidates in-flight responses when a user forgets or loses the connection.
const fragment = new URLSearchParams(location.hash.slice(1));
const expectedFingerprint = fragment.get('fingerprint') || '';
$('pair-code').value = fragment.get('code') || '';
history.replaceState(null, '', location.pathname); // Invitation codes stay out of subsequent URLs/referrers.
if (FINGERPRINT_PATTERN.test(expectedFingerprint)) $('fingerprint').textContent = `Expected desktop certificate: ${expectedFingerprint}`;
$('device-name').maxLength = MAX_DEVICE_NAME_CHARS;
$('pair-code').maxLength = MAX_DEVICE_NAME_CHARS;
$('prompt').maxLength = MAX_PROMPT_CHARS;
$('context-title').maxLength = PHONE_CONTEXT_TITLE_CHARS;
$('context-text').maxLength = PHONE_CONTEXT_TEXT_CHARS;

function notice(text) { $('notice').textContent = text; }
function saveSession() {
  try {
    if (token) sessionStorage.setItem(PHONE_SESSION_KEY, JSON.stringify({ token, runId: currentRun }));
    else sessionStorage.removeItem(PHONE_SESSION_KEY);
  } catch { notice('This browser cannot retain a tab connection. Keep this page open while using it.'); }
}
function forget() {
  connectionEpoch++;
  token = ''; pending = null; currentRun = null; currentApproval = null; preview = null; selectedTask = null;
  clearTimeout(pairingTimer); clearTimeout(runTimer); saveSession();
  $('workspace').hidden = true; $('pair-panel').hidden = false; $('pair-button').disabled = false;
  $('history').replaceChildren(); $('tasks').replaceChildren(); $('reply').textContent = ''; $('context-preview').hidden = true;
  $('context-text').value = ''; $('context-title').value = ''; $('prompt').value = ''; $('run-panel').hidden = true;
  $('connection').textContent = 'Your desktop stays in charge of tools and approvals.';
}
async function api(route, { method = 'GET', body, secret } = {}) {
  const epoch = connectionEpoch;
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), PHONE_REQUEST_TIMEOUT_MS);
  try {
    const headers = {};
    if (token) headers.authorization = `Bearer ${token}`;
    if (body !== undefined) headers['content-type'] = 'application/json';
    if (secret) headers['x-pair-secret'] = secret;
    const response = await fetch(route, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'omit', cache: 'no-store', signal: controller.signal });
    const data = await response.json();
    if (epoch !== connectionEpoch) throw Object.assign(new Error('The phone connection changed.'), { name: 'StaleConnection' });
    if (!response.ok) {
      if (response.status === 401 && token) forget();
      throw new Error(data.error || 'The desktop did not accept this request.');
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('The desktop is unreachable. Check the network, certificate trust and that Ankita is open, then try again.');
    throw error;
  } finally { clearTimeout(timer); }
}
const perform = action => { void Promise.resolve().then(action).catch(error => { if (error.name !== 'StaleConnection') notice(error.message); }); };
function text(tag, value) { const node = document.createElement(tag); node.textContent = value; return node; }
function setSending() {
  $('send').disabled = sending || Boolean(currentRun);
  $('send').textContent = selectedTask ? 'Continue saved request' : 'Send request';
  $('prompt-label').hidden = Boolean(selectedTask); $('prompt').required = !selectedTask;
  $('resume-label').hidden = !selectedTask; $('clear-task').hidden = !selectedTask;
  $('resume-label').textContent = selectedTask ? `Continue: ${selectedTask.goal}. Saved results and selected context stay with this request. Uncertain actions still need review.` : '';
}
async function removeContext() {
  const old = preview; preview = null; $('context-preview').hidden = true; $('context-reviewed').checked = false;
  if (old && token) await api(`${PHONE_ROUTES.context}/${old.id}`, { method: 'DELETE' });
}
async function chooseTask(task) {
  if (currentRun) throw new Error('Stop or finish the current request before choosing saved work.');
  await removeContext(); selectedTask = task; setSending();
  $('request-title').scrollIntoView({ behavior: 'auto', block: 'start' }); $('send').focus();
}
async function refreshWork() {
  const [history, tasks] = await Promise.all([api(PHONE_ROUTES.history), api(PHONE_ROUTES.tasks)]);
  if (!token) return;
  $('history').replaceChildren(...history.messages.map(message => {
    const article = document.createElement('article'); article.append(text('strong', message.role === 'user' ? 'You' : 'Ankita'), text('p', message.content)); return article;
  }));
  if (!history.messages.length) $('history').append(text('p', 'No messages yet. Send your first request below.'));
  $('tasks').replaceChildren(...tasks.tasks.map(task => {
    const article = document.createElement('article'); article.append(text('strong', task.goal), text('p', task.status.replaceAll('_', ' ')));
    for (const item of task.checklist) article.append(text('p', `${item.status}: ${item.content}`));
    for (const reference of task.references) article.append(text('p', `Saved context · ${reference.name}: ${reference.excerpt}${reference.truncated ? ' (excerpt)' : ''}`));
    if (task.receipts.length) {
      const details = document.createElement('details'); details.append(text('summary', 'Review saved actions'));
      for (const receipt of task.receipts) details.append(text('p', `${receipt.tool} · ${receipt.phase}${receipt.failed ? ' · failed' : ''}: ${receipt.result}`));
      article.append(details);
    }
    if (task.reply) article.append(text('p', task.reply));
    if (task.detailsOmitted) article.append(text('p', 'This is a short preview. More saved details are available on the desktop.'));
    if (task.resumable) { const button = text('button', 'Review and continue'); button.type = 'button'; button.className = 'secondary'; button.addEventListener('click', () => perform(() => chooseTask(task))); article.append(button); }
    return article;
  }));
  if (!tasks.tasks.length) $('tasks').append(text('p', 'No saved work in this conversation yet. New requests appear here.'));
}
async function connected() {
  const capabilities = await api(PHONE_ROUTES.capabilities);
  if (expectedFingerprint && capabilities.fingerprint !== expectedFingerprint) {
    await api(PHONE_ROUTES.revoke, { method: 'POST', body: {} }); forget(); throw new Error('The desktop fingerprint differs from the invitation. Create a new invitation on the desktop.');
  }
  $('connection').textContent = `${capabilities.computer} · ${capabilities.teammate?.name || 'Choose a teammate on the desktop'}`;
  $('workspace').hidden = false; $('pair-panel').hidden = true; await refreshWork(); setSending();
  if (currentRun) void pollRun();
}
async function pollPairing() {
  if (!pending) return;
  const request = pending;
  try {
    const result = await api(`${PHONE_ROUTES.pair}/${request.requestId}`, { secret: request.secret });
    if (pending !== request) return;
    if (result.status === 'claimed' && result.token) { token = result.token; pending = null; saveSession(); notice('Phone approved. You can now use its assigned conversation.'); await connected(); return; }
    if (result.status !== 'pending' && result.status !== 'approved') throw new Error('This pairing request expired or was rejected. Create a new code on the desktop.');
    pairingTimer = setTimeout(pollPairing, PHONE_POLL_MS);
  } catch (error) { if (pending !== request) return; pending = null; $('pair-button').disabled = false; notice(error.message); }
}
async function pollRun() {
  const id = currentRun;
  if (!id || !token) return;
  try {
    const run = await api(`${PHONE_ROUTES.runs}/${id}`);
    if (currentRun !== id || !token) return;
    $('run-panel').hidden = false; $('run-status').textContent = run.error || run.status;
    $('reply').textContent = run.reply || run.events.filter(event => event.type === 'message').map(event => event.detail).join('');
    currentApproval = run.pending; $('approval').hidden = !currentApproval;
    $('approval-detail').textContent = currentApproval ? `${currentApproval.name}\n${currentApproval.detail}` : '';
    $('cancel-run').hidden = TERMINAL.has(run.status);
    if (TERMINAL.has(run.status)) { currentRun = null; currentApproval = null; saveSession(); setSending(); await refreshWork(); return; }
    runTimer = setTimeout(pollRun, PHONE_POLL_MS);
  } catch (error) {
    if (currentRun !== id) return;
    notice(`${error.message} Refresh work to check again.`); $('refresh').disabled = false;
    // An expired run must not permanently disable sending after a desktop restart.
    currentRun = null; currentApproval = null; saveSession(); setSending();
  }
}
$('pair-form').addEventListener('submit', event => {
  event.preventDefault(); if (pairingBusy || pending) return; pairingBusy = true; $('pair-button').disabled = true;
  perform(async () => {
    try {
      pending = await api(PHONE_ROUTES.pair, { method: 'POST', body: { code: $('pair-code').value, deviceName: $('device-name').value.trim(), platform: PLATFORM } });
      $('pair-code').value = ''; $('pair-status').textContent = 'Waiting for approval on the desktop. Check the phone name there.'; void pollPairing();
    } finally { pairingBusy = false; if (!pending) $('pair-button').disabled = false; }
  });
});
$('preview-context').addEventListener('click', () => perform(async () => {
  await removeContext(); preview = await api(PHONE_ROUTES.context, { method: 'POST', body: { title: $('context-title').value, text: $('context-text').value, ...(selectedTask ? { taskId: selectedTask.id } : {}) } });
  notice('');
  $('preview-title').textContent = preview.context.title; $('preview-text').textContent = preview.context.text; $('context-preview').hidden = false; $('context-reviewed').focus();
}));
for (const id of ['context-title', 'context-text']) $(id).addEventListener('input', () => { if (preview) perform(removeContext); });
$('remove-context').addEventListener('click', () => perform(async () => { await removeContext(); $('context-text').value = ''; $('context-title').value = ''; }));
$('clear-task').addEventListener('click', () => perform(async () => { await removeContext(); selectedTask = null; setSending(); }));
$('request-form').addEventListener('submit', event => {
  event.preventDefault(); if (sending || currentRun) return;
  perform(async () => {
    if (($('context-text').value.trim() || preview) && (!preview || !$('context-reviewed').checked)) throw new Error('Review the selected context and check the box, or remove it before sending.');
    sending = true; setSending();
    try {
      const body = { version: PHONE_PAIRING_PROTOCOL_VERSION, ...(preview ? { contextId: preview.id } : {}), ...(!selectedTask ? { prompt: $('prompt').value } : {}) };
      const run = await api(selectedTask ? `${PHONE_ROUTES.tasks}/${selectedTask.id}/resume` : PHONE_ROUTES.runs, { method: 'POST', body });
      currentRun = run.id; preview = null; selectedTask = null; saveSession();
      $('prompt').value = ''; $('context-text').value = ''; $('context-title').value = ''; $('context-preview').hidden = true; $('context-reviewed').checked = false;
      notice('Request started on your desktop.'); void pollRun();
    } finally { sending = false; setSending(); }
  });
});
for (const [id, allow] of [['allow', true], ['deny', false]]) $(id).addEventListener('click', () => perform(async () => {
  if (!currentRun || !currentApproval) return;
  await api(`${PHONE_ROUTES.runs}/${currentRun}/approvals/${currentApproval.id}`, { method: 'POST', body: { allow } });
  currentApproval = null; $('approval').hidden = true; clearTimeout(runTimer); await pollRun();
}));
$('cancel-run').addEventListener('click', () => perform(async () => { if (!currentRun) return; await api(`${PHONE_ROUTES.runs}/${currentRun}`, { method: 'DELETE' }); clearTimeout(runTimer); await pollRun(); }));
$('refresh').addEventListener('click', () => perform(async () => { await refreshWork(); if (currentRun) { clearTimeout(runTimer); await pollRun(); } }));
$('disconnect').addEventListener('click', () => perform(async () => { await api(PHONE_ROUTES.revoke, { method: 'POST', body: {} }); forget(); notice('Disconnected. The desktop revoked this tab’s key.'); }));
$('forget').addEventListener('click', () => { forget(); notice('Forgot this tab’s connection. You can also remove the paired phone in desktop Settings.'); });
try { const saved = JSON.parse(sessionStorage.getItem(PHONE_SESSION_KEY) || 'null'); token = saved?.token || ''; currentRun = saved?.runId || null; } catch { /* A new tab can still pair without storage. */ }
if (token) perform(connected);
