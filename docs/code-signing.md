# Code signing Ankita

Signing removes the Windows "Unknown publisher" / SmartScreen warning and lets
auto-updates be trusted. It is optional — unsigned builds still run (users click
**More info → Run anyway**).

The repo is already wired for signing. You only need to obtain credentials and
add them as GitHub secrets; the release workflow then signs automatically.

- **Option A — Azure Trusted Signing** (recommended): ~US$10/month, no hardware
  token, works well in CI. This is what `electron-builder.signing.yml` targets.
- **Option B — a classic `.pfx` certificate**: if you already own a code-signing
  cert (OV), skip to that section.

Microsoft's own guide: <https://learn.microsoft.com/azure/trusted-signing/>

---

## Option A — Azure Trusted Signing

You need an Azure subscription (pay-as-you-go is fine). The Basic tier is a few
dollars a month plus per-signature fees.

### 1. Create a Trusted Signing account
1. Sign in to the [Azure portal](https://portal.azure.com).
2. Search **Trusted Signing** → **Create**.
3. Pick a supported region (e.g. **East US** / **West Europe**), name the
   account, choose the **Basic** tier, create.
4. Open the account and copy the **Endpoint URL** — it looks like
   `https://eus.codesigning.azure.net/`. → this becomes `AZURE_CODE_SIGNING_ENDPOINT`.
   The account **name** becomes `AZURE_CODE_SIGNING_ACCOUNT`.

### 2. Identity validation
Trusted Signing verifies who you are before issuing certificates.
1. In the Trusted Signing account, open **Identity validations** → **New**.
2. Choose **Individual** (personal) or **Organization** (business).
3. Complete the verification (legal name, address, documents). This can take a
   few days and is done once.
4. The **legal name you verify is your publisher name** → `AZURE_PUBLISHER_NAME`.
   It must match exactly (e.g. `Krish Sharma` or `Example LLC`).

### 3. Create a certificate profile
1. In the account, open **Certificate profiles** → **Create**.
2. Type **Public Trust**, pick the identity validation from step 2.
3. Name it (e.g. `ankita`) → `AZURE_CERT_PROFILE`.

### 4. Create an app for GitHub Actions
1. **Microsoft Entra ID** → **App registrations** → **New registration**. Name it
   `ankita-signing`.
2. Copy **Application (client) ID** → `AZURE_CLIENT_ID` and
   **Directory (tenant) ID** → `AZURE_TENANT_ID`.
3. **Certificates & secrets** → **New client secret** → copy the **Value** →
   `AZURE_CLIENT_SECRET`.
4. Give the app permission to sign: open the **Trusted Signing account** →
   **Access control (IAM)** → **Add role assignment** → role
   **Trusted Signing Certificate Profile Signer** → assign to the app.

### 5. Add the GitHub secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
| --- | --- |
| `AZURE_TENANT_ID` | Directory (tenant) ID |
| `AZURE_CLIENT_ID` | Application (client) ID |
| `AZURE_CLIENT_SECRET` | Client secret value |
| `AZURE_PUBLISHER_NAME` | The verified legal name |
| `AZURE_CODE_SIGNING_ENDPOINT` | `https://<region>.codesigning.azure.net/` |
| `AZURE_CODE_SIGNING_ACCOUNT` | Trusted Signing account name |
| `AZURE_CERT_PROFILE` | Certificate profile name |

### 6. Release
Push a version tag (see [`releasing.md`](./releasing.md)). The workflow detects
`AZURE_CLIENT_ID` and builds with `--config electron-builder.signing.yml`, which
signs the app, installer, and uninstaller.

### 7. Verify
Download the installer and run in PowerShell:
```powershell
Get-AuthenticodeSignature .\Ankita-2.0.0-setup-x64.exe | Format-List Status, SignerCertificate
```
`Status` should be **Valid** and the signer should be your publisher name.

---

## Option B — classic `.pfx` certificate

If you have an OV code-signing certificate exported as a `.pfx`:

1. Base64-encode it:
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\path\cert.pfx")) | Set-Clipboard
   ```
2. Add two GitHub secrets:
   - `WIN_CSC_LINK` — the base64 string (or a URL to the pfx).
   - `WIN_CSC_KEY_PASSWORD` — the pfx password.
3. The workflow passes these to electron-builder as `CSC_LINK` /
   `CSC_KEY_PASSWORD`; no config change needed. Keep the `.pfx` out of the repo.

---

## Building a signed release locally

```powershell
$env:AZURE_TENANT_ID="…"; $env:AZURE_CLIENT_ID="…"; $env:AZURE_CLIENT_SECRET="…"
$env:AZURE_PUBLISHER_NAME="…"; $env:AZURE_CODE_SIGNING_ENDPOINT="https://eus.codesigning.azure.net/"
$env:AZURE_CODE_SIGNING_ACCOUNT="…"; $env:AZURE_CERT_PROFILE="…"
npm run desktop:build
npx electron-builder --win --publish never --config electron-builder.signing.yml
```

Or, for a `.pfx`:
```powershell
$env:CSC_LINK="C:\path\cert.pfx"; $env:CSC_KEY_PASSWORD="…"
npm run desktop:package
```

Local unsigned builds are unaffected: `electron-builder.yml` alone never signs.

## Notes

- **Publisher name matters.** Windows shows the certificate's subject. For
  Trusted Signing that is the verified legal identity; using a nickname will not
  match.
- **Reputation.** SmartScreen can still warn briefly for new certificates until
  download reputation builds; EV / Trusted Signing generally clear faster.
- **macOS** uses a Developer ID certificate and notarization instead — add a
  separate `mac` signing config when you build for macOS.
