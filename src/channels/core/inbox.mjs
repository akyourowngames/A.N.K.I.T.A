/** One FIFO per conversation and a shared single-flight gate per agent target. */
export class ChannelInbox {
  constructor() { this.chains = new Map(); this.targets = new Map(); this.controllers = new Map(); this.generations = new Map(); this.stopped = false; }
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
      try {
        await previousTarget.catch(() => {});
        if (this.stopped || controller.signal.aborted || generation !== (this.generations.get(key) || 0)) return;
        return await work({ signal: controller.signal });
      } finally {
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
