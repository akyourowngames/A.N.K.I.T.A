import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import publisher from '../vendor/openai-tunnel/source.json' with { type: 'json' };
import { NATIVE_TUNNEL_RESOURCE_DIRECTORY, nativeTunnelResourcesReady } from '../src/integrations/chatgpt-browser/native-tunnel.mjs';
import './build-chatgpt-companion.mjs';

const ROOT = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url))); // Build checkout discovery, never a user profile path.
const MAX_ARCHIVE_BYTES = 256 * 1024 * 1024; // Bytes/publisher archive; reject an unbounded download before extraction.
const DOWNLOAD_TIMEOUT_MS = 120 * 1000; // Milliseconds/build-only download; never a runtime dependency download.
const ARCHIVE_NAME = 'native-tunnel.zip'; const SCRATCH_PREFIX = 'ankita-native-bundle-';
const EXTRACT_DIRECTORY = 'extracted';
const EXTRACTION_SHELL_CANDIDATES = Object.freeze(['pwsh.exe', 'powershell.exe']); // Prefer the current PowerShell runtime, then Windows PowerShell 5.1.
const BUILDER_CONFIG = 'desktop/packaging/electron-builder.yml'; // Checked-in generated signing projection; publisher metadata stays the single source of member names.
const SIGNING_BEGIN = '  # BEGIN publisher signing exclusions (generated from vendor/openai-tunnel/source.json)';
const SIGNING_END = '  # END publisher signing exclusions';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const option = name => { const index = process.argv.indexOf(name); return index < 0 ? null : process.argv[index + 1]; };
async function extractArchive(archiveFile, destination) {
  const script = fileURLToPath(new URL('./extract-native-tunnel.ps1', import.meta.url));
  const failures = [];
  for (const executable of EXTRACTION_SHELL_CANDIDATES) {
    const result = await new Promise(resolve => {
      const child = spawn(executable, ['-NoProfile', '-File', script, '-Archive', archiveFile, '-Destination', destination], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
      let errorText = '';
      child.stderr.setEncoding('utf8'); child.stderr.on('data', chunk => { errorText += chunk; });
      child.once('error', error => resolve({ code: null, error: error.message }));
      child.once('exit', code => resolve({ code, error: errorText.trim() }));
    });
    if (result.code === 0) return;
    failures.push(`${executable}: ${result.error || `exit ${result.code ?? 'unknown'}`}`);
  }
  throw new Error(`Native publisher archive extraction failed (${failures.join('; ')})`);
}
const target = option('--target') ?? `${process.platform}-${process.arch}`;
const artifact = publisher.targets[target];
const nativeOutput = path.join(ROOT, 'desktop', NATIVE_TUNNEL_RESOURCE_DIRECTORY, target); // Target-specific build resources, never profile data.
const cachedArtifact = artifact && { ...artifact, binary: path.join(nativeOutput, artifact.filename), companionBinary: path.join(nativeOutput, artifact.companionFilename) };
const builderFile = path.join(ROOT, BUILDER_CONFIG), builderText = fs.readFileSync(builderFile, 'utf8');
const signingStart = builderText.indexOf(SIGNING_BEGIN), signingEnd = builderText.indexOf(SIGNING_END);
if (signingStart < 0 || signingEnd <= signingStart) throw new Error('Native publisher signing projection is missing');
const signExts = [...new Set(Object.values(publisher.targets).flatMap(item => [item.filename, item.companionFilename]))];
if (signExts.some(filename => path.basename(filename) !== filename || !/^[a-zA-Z0-9._-]+$/.test(filename))) throw new Error('Invalid publisher signing member');
const projection = SIGNING_BEGIN + '\n  signExts:\n' + signExts.map(filename => `    - '!${filename}'`).join('\n') + '\n';
fs.writeFileSync(builderFile, builderText.slice(0, signingStart) + projection + builderText.slice(signingEnd));
if (!artifact) {
  fs.mkdirSync(path.join(ROOT, 'desktop', NATIVE_TUNNEL_RESOURCE_DIRECTORY), { recursive: true });
  console.log(JSON.stringify({ event: 'chatgpt-resources-ready', companion: true, nativeTarget: target, nativeTransport: 'unsupported' }));
} else if (!option('--archive') && nativeTunnelResourcesReady(cachedArtifact)) {
  console.log(JSON.stringify({ event: 'chatgpt-resources-ready', companion: true, nativeTarget: target, cached: true, primaryMatched: true, forwardingHelperMatched: true, notices: artifact.notices.length, binariesExecuted: false }));
} else {
  if (process.platform !== 'win32') throw new Error('The verified Windows native archive requires Windows PowerShell extraction');
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), SCRATCH_PREFIX));
  const extract = path.join(scratch, EXTRACT_DIRECTORY), supplied = option('--archive');
  try {
    let archive;
    if (supplied) archive = fs.readFileSync(path.resolve(supplied));
    else {
      const response = await fetch(artifact.archiveUrl, { signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS) });
      if (!response.ok || !response.body || Number(response.headers.get('content-length')) > MAX_ARCHIVE_BYTES) throw new Error('Native publisher archive download failed');
      const chunks = []; let size = 0;
      for await (const chunk of response.body) { size += chunk.length; if (size > MAX_ARCHIVE_BYTES) throw new Error('Native publisher archive exceeds its byte limit'); chunks.push(chunk); }
      archive = Buffer.concat(chunks);
    }
    if (archive.length > MAX_ARCHIVE_BYTES || hash(archive) !== artifact.archiveSha256) throw new Error('Native publisher archive checksum mismatch');
    const archiveFile = path.join(scratch, ARCHIVE_NAME); fs.writeFileSync(archiveFile, archive); fs.mkdirSync(extract);
    await extractArchive(archiveFile, extract);
    if (hash(fs.readFileSync(path.join(extract, artifact.filename))) !== artifact.sha256 ||
        hash(fs.readFileSync(path.join(extract, artifact.companionFilename))) !== artifact.companionSha256) throw new Error('Native publisher member checksum mismatch');
    const output = path.join(ROOT, 'desktop', NATIVE_TUNNEL_RESOURCE_DIRECTORY, target); fs.mkdirSync(output, { recursive: true });
    const canonical = fs.realpathSync(output), relative = path.relative(ROOT, canonical);
    if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Native build output escapes the checkout');
    for (const filename of [artifact.filename, artifact.companionFilename, ...artifact.notices]) {
      if (path.basename(filename) !== filename) throw new Error('Invalid native publisher member name');
      const source = path.join(extract, filename);
      if (!fs.statSync(source).isFile() || fs.lstatSync(source).isSymbolicLink()) throw new Error('Native publisher notice or member is missing');
      const destination = path.join(canonical, filename);
      if (fs.existsSync(destination) && fs.lstatSync(destination).isSymbolicLink()) throw new Error('Native output member cannot be a link');
      fs.copyFileSync(source, destination);
    }
    console.log(JSON.stringify({ event: 'chatgpt-resources-ready', companion: true, nativeTarget: target, publisherArchiveMatched: true,
      primaryMatched: true, forwardingHelperMatched: true, notices: artifact.notices.length, binariesExecuted: false, independentScan: 'unavailable' }));
  } finally {
    const resolved = fs.realpathSync(scratch), relative = path.relative(fs.realpathSync(os.tmpdir()), resolved);
    if (!relative.startsWith('..') && !path.isAbsolute(relative) && path.basename(resolved).startsWith(SCRATCH_PREFIX)) fs.rmSync(resolved, { recursive: true, force: true });
  }
}
