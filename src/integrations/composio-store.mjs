import fs from 'node:fs';
import path from 'node:path';

export class ComposioStore {
  constructor(file) {
    this.file = file;
    this.data = { version: 1, userId: null, sessionId: null, broker: null, aliases: {} };
  }

  load() {
    try {
      const value = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      this.data = {
        version: 1,
        userId: typeof value.userId === 'string' ? value.userId : null,
        sessionId: typeof value.sessionId === 'string' ? value.sessionId : null,
        broker: value.broker && typeof value.broker === 'object' ? value.broker : null,
        aliases: value.aliases && typeof value.aliases === 'object' ? value.aliases : {},
      };
    } catch {
      this.data = { version: 1, userId: null, sessionId: null, broker: null, aliases: {} };
    }
    return this;
  }

  update(patch) {
    this.load();
    this.data = { ...this.data, ...patch, version: 1 };
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = path.join(path.dirname(this.file), `.${path.basename(this.file)}.${process.pid}.tmp`);
    try {
      fs.writeFileSync(tmp, `${JSON.stringify(this.data, null, 2)}\n`, { mode: 0o600 });
      fs.renameSync(tmp, this.file);
      fs.chmodSync(this.file, 0o600);
    } finally {
      try { fs.unlinkSync(tmp); } catch {}
    }
    return this;
  }
}
