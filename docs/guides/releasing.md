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
`.github/workflows/release.yml` runs on pushes to `ankita`, `v*` tags and manual
dispatch. A branch run creates the version tag itself. Publish only after both
the local checks and completed remote workflow pass.

1. Bump `package.json` and the root version entries in `package-lock.json`:

   ```bash
   npm version minor --no-git-tag-version --ignore-scripts
   ```

2. Add a dated `## [<version>]` section to `CHANGELOG.md`. The workflow extracts
   that section for the release description. Update the README and guides for
   changed setup or behavior.
3. Run focused tests, `npm test` (serial), `npm run desktop:build`, the relevant
   live checks and `git diff --check`. For package/resource changes, exercise an
   unpacked Windows build too.
4. Inspect the staged path list and diff. Include code, tests, docs, manifests,
   lockfile and required app assets. Exclude `.commandcode/`, `launch-video/`,
   generated films, logs, dumps, user data and local release binaries. To remove
   an already-tracked generated file while retaining it locally, use
   `git rm --cached -- <path>` and add its ignore rule.
5. Commit and push `ankita`. Do not also push a matching tag for the branch run;
   the workflow creates it pointing at that commit.
6. Inspect the workflow for that exact commit until it completes successfully.
   Then inspect the release and all expected assets, including `latest.yml`.
   A pushed branch or created tag alone does not prove publication.

The Windows workflow installs the lockfile, requires `npm test`, derives the
version from `package.json`, and checks whether that version already has an update
manifest. If it needs publishing, it builds with `--publish never`, then uploads
the installer, portable executable, blockmap and manifest in one deterministic
GitHub CLI step. It prefers the hand-written changelog over generated notes.

Keep the tag and `package.json` version in sync (`v2.1.0` ↔ `2.1.0`… use the
same number). electron-builder names artifacts from `package.json`. An existing
release without `latest.yml` is incomplete and the workflow retries its uploads.

For an explicit tag release, first verify and commit the version, then push only
the matching `v<version>` tag for that route. For retries, use workflow dispatch.

```bash
gh run list --workflow release.yml --branch ankita --limit 5
gh run view <run-id> --json status,conclusion,headSha,url,jobs
gh release view v<version> --json tagName,targetCommitish,assets,url
```

Check the manifest version, installer path/size and SHA-512 against the downloaded
setup executable. The tagged commit must match the verified release commit.

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
