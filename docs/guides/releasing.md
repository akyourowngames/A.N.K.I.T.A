# Releasing Ankita (GitHub Releases + auto-update)

Ankita publishes to **GitHub Releases** and installed builds update themselves.
The publish target is configured in `desktop/packaging/electron-builder.yml`:

```yaml
publish:
  provider: github
  owner: akyourowngames
  repo: A.N.K.I.T.A
```

## How auto-update works

- On launch (after ~6s) an **installed** build checks GitHub Releases for a
  newer version. It also runs from **Help → Check for updates…**.
- A newer release is downloaded in the background; when ready the app shows a
  "Restart & update" banner (`desktop/renderer/src/components/UpdateBanner.tsx`).
- Background checks are silent unless there is something to act on; manual
  checks report "up to date" and errors.
- Implementation: `desktop/electron/updater.mjs` (electron-updater) wired in
  `desktop/electron/main.mjs`; events are sent to the renderer as `update:event`.

Only the **NSIS-installed** build self-updates. The **portable** exe is a
single-file bundle and reports "This build updates through its installer" — its
users re-download. A dev run (`desktop:dev`) never checks.

Requirements for an update to apply: the release version must be **higher** than
the installed `package.json` version, and the release must include the setup exe,
its `.blockmap`, and `latest.yml` (all produced automatically).

## Cutting a release

### Option A — GitHub Actions (recommended)
`.github/workflows/release.yml` builds and publishes on a version tag.

1. Bump `version` in `package.json` (e.g. `2.0.0` → `2.1.0`).
2. Commit and push.
3. Tag and push the tag:

   ```bash
   git tag v2.1.0
   git push origin v2.1.0
   ```

4. The workflow runs on `windows-latest`, builds the renderer, and runs
   `electron-builder --win --publish always` with `GITHUB_TOKEN`. The release
   appears under **Releases** with the installer and update metadata.

Keep the tag and `package.json` version in sync (`v2.1.0` ↔ `2.1.0`… use the
same number). electron-builder names artifacts from `package.json`.

### Option B — publish from your machine
Needs a token with `repo` scope (the `gh` CLI token works):

```bash
# PowerShell
$env:GH_TOKEN = (gh auth token)
npm run desktop:release
```

`desktop:release` builds the renderer and runs `electron-builder --win --publish always`.

## What gets uploaded

| File | Purpose |
| --- | --- |
| `Ankita-<version>-setup-x64.exe` | Installer (the auto-update payload) |
| `Ankita-<version>-setup-x64.exe.blockmap` | Differential downloads |
| `latest.yml` | The update manifest the app checks |
| `Ankita-<version>-portable-x64.exe` | Standalone, for direct download |

Build locally without publishing: `npm run desktop:package`.

## Notes

- **Code signing.** Builds are unsigned by default, so SmartScreen warns on
  first run and auto-updates are not reputation-signed. The repo is already wired
  for it — see [`code-signing.md`](./code-signing.md) to add credentials and
  turn it on (Azure Trusted Signing, or a classic `.pfx`).
- **Pre-releases.** Mark a GitHub release as a pre-release to keep it off the
  normal `latest` channel.
- **Rollback.** Re-publish a higher version; clients only move forward.
- **Non-Windows.** `mac` and `linux` targets are declared but should be built on
  their own runners and added to the workflow `matrix` when needed.
