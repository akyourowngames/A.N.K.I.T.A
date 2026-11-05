import fs from 'node:fs';

// Disposable fixtures only. Ten retries with a 100 ms base delay let native handles settle without blocking their close callbacks.
const FIXTURE_CLEANUP = Object.freeze({ recursive: true, force: true, maxRetries: 10, retryDelay: 100 });

export function removeFixtureDirectory(directory) {
  return fs.promises.rm(directory, FIXTURE_CLEANUP);
}
