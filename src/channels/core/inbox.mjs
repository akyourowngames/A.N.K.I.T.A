/** One FIFO per conversation and a shared single-flight gate per agent target. */
export class ChannelInbox {
  constructor({ maxConcurrent = Infinity } = {}) {
    this.chains = new Map(); this.targets = new Map(); this.controllers = new Map(); this.generations = new Map(); this.stopped = false;
    this.maxConcurrent = maxConcurrent; this.active = 0; this.waiting = [];
  }
  acquire(signal) {
    if (signal.aborted || this.stopped) return Promise.resolve(false);
    if (this.active < this.maxConcurrent) { this.active++; return Promise.resolve(true); }
    return new Promise(resolve => {
      const entry = { signal, resolve, abort: () => { this.waiting = this.waiting.filter(item => item !== entry); resolve(false); } };
      signal.addEventListener('abort', entry.abort, { once: true }); this.waiting.push(entry);
    });
  }
  release() {
    this.active--;
    while (this.waiting.length) {
      const entry = this.waiting.shift(); entry.signal.removeEventListener('abort', entry.abort);
      if (entry.signal.aborted || this.stopped) { entry.resolve(false); continue; }
      this.active++; entry.resolve(true); break;
    }
  }
  enqueue(key, work, { target = key, signal } = {}) {
    if (this.stopped) return Promise.reject(new Error('Channel inbox stopped'));
    const generation = this.generations.get(key) || 0;
    const previous = this.chains.get(key) || Promise.resolve();
    const execute = async () => {
      if (this.stopped || generation !== (this.generations.get(key) || 0) || signal?.aborted) return;
      const controller = new AbortController();
      const cancel = () => controller.abort(signal.reason);
      signal?.addEventListener('abort', cancel, { once: true });
      this.controllers.set(key, controller);
      const previousTarget = this.targets.get(target) || Promise.resolve();
      let release;
      const gate = new Promise(resolve => { release = resolve; });
      const held = previousTarget.catch(() => {}).then(() => gate);
      this.targets.set(target, held);
      let acquired = false;
      try {
        await previousTarget.catch(() => {});
        if (this.stopped || controller.signal.aborted || generation !== (this.generations.get(key) || 0)) return;
        acquired = await this.acquire(controller.signal);
        if (!acquired) return;
        return await work({ signal: controller.signal });
      } finally {
        if (acquired) this.release();
        signal?.removeEventListener('abort', cancel);
        if (this.controllers.get(key) === controller) this.controllers.delete(key);
        release();
        if (this.targets.get(target) === held) this.targets.delete(target);
      }
    };
    const next = previous.catch(() => {}).then(execute).finally(() => { if (this.chains.get(key) === next) this.chains.delete(key); });
    this.chains.set(key, next);
    return next;
  }
  cancel(key) {
    this.generations.set(key, (this.generations.get(key) || 0) + 1);
    this.controllers.get(key)?.abort(new DOMException('Channel task cancelled', 'AbortError'));
  }
  async stop() {
    this.stopped = true;
    for (const key of this.chains.keys()) this.cancel(key);
    await Promise.allSettled([...this.chains.values()]);
  }
}
