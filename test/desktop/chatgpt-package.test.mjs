import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chatgptResourcePaths, verifyCompanionResources } from '../../desktop/electron/chatgpt-resources.mjs';
import { createRequire } from 'node:module';
import publisher from '../../vendor/openai-tunnel/source.json' with { type: 'json' };

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const BUILDER_CONFIG = new URL('../../desktop/packaging/electron-builder.yml', import.meta.url);
const require = createRequire(import.meta.url);
const yaml = require('js-yaml');
const { FileMatcher } = require('app-builder-lib/out/fileMatcher.js');
const PACKAGED_SOURCE_ROOTS = ['desktop', 'services', 'src', 'tools', 'skills', 'vendor']; // Local trees that can contribute shipped modules.
const PACKAGED_MODULE_EXTENSIONS = /\.(?:mjs|js|cjs|mts|json)$/;
const RELATIVE_IMPORTS = [/\b(?:import|export)\s+(?:[^'"`;]*?\s+from\s+)?['"]([^'"]+)['"]/g, /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g];

test('packaged companion and native helper resolve through real resources outside ASAR and missing extension fails closed', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-package-resources-')); t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const paths = chatgptResourcePaths({ packageRoot: path.join(directory, 'app.asar'), resourcesPath: directory, isPackaged: true });
  assert.equal(paths.companionPath, path.join(directory, 'chatgpt-companion'));
  assert.equal(paths.nativeResourceRoot, path.join(directory, 'native-tunnel'));
  assert.throws(() => verifyCompanionResources(paths.companionPath), /missing/);
  fs.cpSync(fileURLToPath(new URL('../../desktop/chatgpt-companion/', import.meta.url)), paths.companionPath, { recursive: true });
  assert.equal(verifyCompanionResources(paths.companionPath), true);
  fs.unlinkSync(path.join(paths.companionPath, 'upstream', 'delivery.js'));
  assert.throws(() => verifyCompanionResources(paths.companionPath), /missing/);
});

test('Windows packaging keeps publisher helper bytes intact while signing ANKITA itself', () => {
  const source = fs.readFileSync(BUILDER_CONFIG, 'utf8');
  require('app-builder-lib'); // The builder's public entry initializes its mutually dependent packager classes.
  const { WinPackager } = require('app-builder-lib/out/winPackager.js');
  for (const newline of ['\n', '\r\n']) {
    const { win } = yaml.load(source.replace(/\r?\n/g, newline), { schema: yaml.JSON_SCHEMA });
    const shouldSign = file => WinPackager.prototype.shouldSignFile.call({ platformSpecificBuildOptions: win }, file);
    for (const target of Object.values(publisher.targets)) {
      assert.equal(shouldSign(target.filename), false, 'The publisher primary hash must survive a signed ANKITA package');
      assert.equal(shouldSign(target.companionFilename), false, 'The publisher forwarding helper hash must survive signing');
    }
    assert.equal(shouldSign('Ankita.exe'), true);
  }
});

test('every local module imported by packaged sources ships inside the ASAR file set', () => {
  const config = yaml.load(fs.readFileSync(BUILDER_CONFIG, 'utf8'), { schema: yaml.JSON_SCHEMA });
  const filter = new FileMatcher(ROOT, ROOT, value => value, config.files).createFilter();
  const isPackaged = file => filter(path.join(ROOT, file), { isDirectory: () => false });
  const files = PACKAGED_SOURCE_ROOTS.filter(root => fs.existsSync(path.join(ROOT, root)))
    .flatMap(root => fs.readdirSync(path.join(ROOT, root), { recursive: true })
      .map(file => path.posix.join(root, String(file).replaceAll('\\', '/'))))
    .filter(file => PACKAGED_MODULE_EXTENSIONS.test(file));
  const missing = new Map();
  for (const file of files.filter(isPackaged)) {
    if (file.endsWith('.json')) continue;
    const text = fs.readFileSync(path.join(ROOT, file), 'utf8');
    for (const pattern of RELATIVE_IMPORTS) {
      pattern.lastIndex = 0;
      for (let match; (match = pattern.exec(text));) {
        if (!match[1]?.startsWith('.')) continue;
        const target = path.posix.normalize(path.posix.join(path.posix.dirname(file), match[1]));
        if (target.startsWith('..') || path.posix.isAbsolute(target) || !fs.existsSync(path.join(ROOT, target)) || isPackaged(target)) continue;
        missing.set(target, [...(missing.get(target) ?? []), file]);
      }
    }
  }
  assert.deepEqual([...missing], [], 'Every relative module imported by packaged code must be included in the ASAR file set');
});

test('release CI prepares pinned companion and native helper resources before either Windows package branch', () => {
  const workflow = fs.readFileSync(new URL('../../.github/workflows/release.yml', import.meta.url), 'utf8');
  const prepare = workflow.indexOf('npm run desktop:resources');
  assert.ok(prepare >= 0, 'a clean release runner must prepare the ignored native resource directory');
  for (const config of ['electron-builder.signing.yml', 'electron-builder.yml']) {
    assert.ok(workflow.indexOf('--config desktop/packaging/' + config) > prepare,
      'both signed and unsigned package routes must follow resource preparation');
  }
});
