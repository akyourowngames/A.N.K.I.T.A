import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { LOCK_STALE_MS } from './job-policy.mjs';
import { writeTextFile } from '../../tools/shared/_shared.mjs';
const TAKEOVER_WAIT_MS = 15_000; // Cooperative owner shutdown deadline; never forcibly steal a live owner.
const TAKEOVER_POLL_MS = 50; // Milliseconds between ownership checks.
const RECOVERY_SUFFIX = '.recovery'; // Exclusive sidecar for recovering a stale owner.
const TAKEOVER_SUFFIX = '.takeover'; // Cooperative owner-shutdown request sidecar.
const OWNERSHIP_ERROR = 'desktop scheduler owns routines — stop the desktop app or pass --takeover (cooperative shutdown required)';
function alive(pid) { try { process.kill(pid, 0); return true; } catch (error) { return error.code === 'EPERM'; } }
export class SchedulerOwnership {
  constructor(file, { host = 'desktop', now = () => Date.now(), takeoverWaitMs = TAKEOVER_WAIT_MS } = {}) {
    Object.assign(this, { file, host, now, takeoverWaitMs }); this.token = randomUUID();
    this.recoveryFile = `${file}${RECOVERY_SUFFIX}`; this.takeoverFile = `${file}${TAKEOVER_SUFFIX}`;
  }
  read() {
    try {
      const owner = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      return owner && Number.isInteger(owner.pid) && owner.pid > 0 && typeof owner.token === 'string' && owner.token && Number.isFinite(owner.heartbeat) ? owner : null;
    } catch { return null; }
  }
  async acquire({ takeover = false } = {}) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const deadline = this.now() + this.takeoverWaitMs;
    for (;;) {
      try {
        const fd = fs.openSync(this.file, 'wx');
        try { fs.writeFileSync(fd, JSON.stringify({ pid: process.pid, host: this.host, token: this.token, heartbeat: this.now() })); }
        finally { fs.closeSync(fd); }
        return true;
      } catch (error) { if (error.code !== 'EEXIST') throw error; }
      let owner = this.read();
      if (!owner || (!alive(owner.pid) && this.now() - owner.heartbeat > LOCK_STALE_MS)) {
        // Serialize both malformed and dead-owner recovery. A token check alone
        // leaves a cross-process gap between checking and unlinking the file.
        let recovery;
        try {
          recovery = fs.openSync(this.recoveryFile, 'wx');
          owner = this.read();
          const stale = owner ? !alive(owner.pid) && this.now() - owner.heartbeat > LOCK_STALE_MS
            : this.now() - fs.statSync(this.file).mtimeMs > LOCK_STALE_MS;
          if (stale) fs.unlinkSync(this.file);
        } catch (error) { if (!['EEXIST', 'ENOENT'].includes(error.code)) throw error; }
        finally { if (recovery !== undefined) { fs.closeSync(recovery); fs.unlinkSync(this.recoveryFile); } }
        if (!fs.existsSync(this.file)) continue;
        owner = this.read();
      }
      // A live PID remains authoritative even when sleep made its heartbeat stale.
      if (!takeover || this.now() >= deadline) throw new Error(OWNERSHIP_ERROR);
      fs.writeFileSync(this.takeoverFile, JSON.stringify({ token: owner?.token, requestedBy: this.host }));
      await delay(TAKEOVER_POLL_MS);
    }
  }
  heartbeat() {
    const owner = this.read();
    if (owner?.token !== this.token) return false;
    try {
      const request = JSON.parse(fs.readFileSync(this.takeoverFile, 'utf8'));
      if (request.token === this.token) return false;
    } catch {}
    writeTextFile(this.file, JSON.stringify({ ...owner, heartbeat: this.now() }), '\n');
    return true;
  }
  release() {
    if (this.read()?.token !== this.token) return false;
    fs.unlinkSync(this.file);
    try { fs.unlinkSync(this.takeoverFile); } catch {}
    return true;
  }
}
