import fs from 'node:fs';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';
import { writeTextFile } from '../tools/_shared.mjs';

export function localClock(now = new Date(), timeZone) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timeZone || undefined, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now);
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, minute: Number(p.hour) * 60 + Number(p.minute) };
}

export function inQuietHours(value = '', now = new Date(), timeZone) {
  if (!value) return false;
  const m = /^(\d{2}):(\d{2})-(\d{2}):(\d{2})$/.exec(value);
  if (!m || +m[1] > 23 || +m[3] > 23 || +m[2] > 59 || +m[4] > 59) throw new Error('QUIET_HOURS must be HH:MM-HH:MM');
  const start = +m[1] * 60 + +m[2], end = +m[3] * 60 + +m[4];
  const { minute } = localClock(now, timeZone);
  return start === end ? false : start < end ? minute >= start && minute < end : minute >= start || minute < end;
}

// Scripts are constant. Notification content is passed as argv/environment data.
const WINDOWS_SCRIPT = `
$ErrorActionPreference = 'Stop'
if (Get-Command New-BurntToastNotification -ErrorAction SilentlyContinue) {
  try { New-BurntToastNotification -Text $env:ANKITA_NOTIFY_TITLE, $env:ANKITA_NOTIFY_BODY; exit 0 } catch {}
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
try {
  $icon.Icon = [System.Drawing.SystemIcons]::Information
  $icon.Visible = $true
  $icon.ShowBalloonTip(10000, $env:ANKITA_NOTIFY_TITLE, $env:ANKITA_NOTIFY_BODY, [System.Windows.Forms.ToolTipIcon]::Info)
  Start-Sleep -Seconds 10
} finally { $icon.Dispose() }
`;

export async function desktopNotify(text, { title = 'ankita', platform = process.platform, exec = promisify(execFile), timeout = 15000 } = {}) {
  const opts = { windowsHide: true, timeout, maxBuffer: 65536 };
  if (platform === 'win32') {
    await exec('powershell.exe', ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(WINDOWS_SCRIPT, 'utf16le').toString('base64')], { ...opts, env: { ...process.env, ANKITA_NOTIFY_TITLE: title, ANKITA_NOTIFY_BODY: text } });
  } else if (platform === 'darwin') {
    await exec('osascript', ['-e', 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run', '--', title, text], opts);
  } else if (platform === 'linux') {
    await exec('notify-send', ['--', title, text], opts);
  } else throw new Error('No desktop notification transport on this platform');
  return 'desktop';
}

export async function sendWebhook(text, config, { fetch = globalThis.fetch } = {}) {
  let url, body, headers = {};
  if (config.ntfyUrl) {
    url = config.ntfyUrl; body = text;
    headers = { 'Content-Type': 'text/plain; charset=utf-8', ...(config.ntfyToken ? { Authorization: `Bearer ${config.ntfyToken}` } : {}) };
  } else if (config.discordWebhookUrl) {
    url = config.discordWebhookUrl;
    body = JSON.stringify({ content: text, allowed_mentions: { parse: [] } });
    headers = { 'Content-Type': 'application/json' };
  } else if (config.pushoverToken && config.pushoverUser) {
    url = 'https://api.pushover.net/1/messages.json';
    body = new URLSearchParams({ token: config.pushoverToken, user: config.pushoverUser, message: text, title: config.agentName || 'ankita' });
  } else return false;
  if (!['https:', 'http:'].includes(new URL(url).protocol)) throw new Error('Notification URL must use HTTP(S)');
  const res = await fetch(url, { method: 'POST', body, headers, redirect: 'error', signal: AbortSignal.timeout((config.notifyTimeout || 10) * 1000) });
  if (!res.ok) throw new Error(`Notification service returned HTTP ${res.status}`);
  if (config.pushoverToken && !config.ntfyUrl && !config.discordWebhookUrl && (await res.json()).status !== 1) throw new Error('Pushover rejected notification');
  return true;
}

export class NotificationDelivery {
  constructor({ config = {}, file = null, telegram = null, webhook = null, desktop = null, print = console.log, log = () => {}, now = () => new Date() } = {}) {
    Object.assign(this, { config, file, telegram, print, log, now });
    this.webhook = webhook || (text => sendWebhook(text, config));
    this.desktop = desktop || (text => desktopNotify(text, { title: config.agentName || 'ankita' }));
    this.queue = [];
    if (file) {
      try {
        this.queue = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (!Array.isArray(this.queue)) throw new Error('Invalid notification queue');
      } catch (err) { if (err.code !== 'ENOENT') throw err; }
    }
    inQuietHours(config.quietHours, now(), config.timeZone);
  }

  save() {
    if (!this.file) return;
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.queue));
  }

  change(fn) {
    if (!this.file) return fn();
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const lock = `${this.file}.lock`;
    let fd;
    try {
      try { if (Date.now() - fs.statSync(lock).mtimeMs > 60000) fs.unlinkSync(lock); } catch {}
      fd = fs.openSync(lock, 'wx');
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
      throw Object.assign(new Error('Notification queue busy; retry delivery'), { code: 'QUEUE_BUSY' });
    }
    try {
      try {
        this.queue = JSON.parse(fs.readFileSync(this.file, 'utf8'));
        if (!Array.isArray(this.queue)) throw new Error('Invalid notification queue');
      } catch (err) { if (err.code !== 'ENOENT') throw err; this.queue = []; }
      const result = fn();
      this.save();
      return result;
    } finally { fs.closeSync(fd); fs.unlinkSync(lock); }
  }

  enqueue(text) {
    if (!String(text).trim()) return 'empty';
    // All channels accept this size; large messages retain every part.
    const chars = Array.from(String(text));
    this.change(() => {
      for (let i = 0; i < chars.length; i += 450) this.queue.push({ id: randomUUID(), at: this.now().toISOString(), text: chars.slice(i, i + 450).join('') });
    });
    return 'queued';
  }

  async deliverNow(text) {
    for (const [name, send] of [['telegram', this.telegram], ['webhook', this.webhook], ['desktop', this.config.desktopNotifications === false ? null : this.desktop]]) {
      if (!send) continue;
      try { if (await send(text) !== false) return name; }
      catch { this.log(`${name} notification failed; trying next channel`); }
    }
    await this.print(text);
    return 'terminal';
  }

  async send(text) {
    await this.queueMessage(text);
    return await this.flush() || 'queued';
  }

  async queueMessage(text) {
    for (let attempt = 0; ; attempt++) {
      try { return this.enqueue(text); }
      catch (err) {
        if (err.code !== 'QUEUE_BUSY' || attempt >= 20) throw err;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
  }

  async flush() {
    if (this.flushing || inQuietHours(this.config.quietHours, this.now(), this.config.timeZone)) return null;
    this.flushing = true;
    let channel = null;
    try {
      // Bound each flush; backlog remains on disk for subsequent ticks.
      for (let batch = 0; batch < 4; batch++) {
        const selected = this.change(() => {
          const selected = [];
          let size = 0;
          for (const item of this.queue) {
            // A lease covers slow network/desktop delivery without holding a
            // filesystem lock or blocking other writers from enqueueing.
            if (item.leaseUntil > Date.now()) continue;
            if (selected.length && size + item.text.length + 2 > 950) break;
            selected.push(item); size += item.text.length + 2;
            item.leaseUntil = Date.now() + Math.max(120000, (this.config.notifyTimeout || 10) * 1000 + 60000);
          }
          return selected;
        });
        if (!selected.length) break;
        const sent = new Set(selected.map(x => x.id));
        try { channel = await this.deliverNow(selected.map(x => x.text).join('\n\n')); }
        catch (err) {
          this.change(() => { for (const item of this.queue) if (sent.has(item.id)) delete item.leaseUntil; });
          throw err;
        }
        this.change(() => { this.queue = this.queue.filter(x => !sent.has(x.id)); });
      }
      return channel;
    } finally { this.flushing = false; }
  }
}
