# Phone pairing

Ankita desktop can pair with the Ankita phone app over the local network. A
paired phone gets its own key and sends requests to the **live desktop
assistant**, so it uses the same teammates, tools, approvals and history as the
desktop window.

This is separate from the browser-extension pairing flow and from the optional
persistent-work companion. Pairing a phone does **not** attach the phone to the
persistent-work service; that service still needs its own worker connection.

## Setup

1. On the desktop, open **Settings → Phone**. Choose the Wi-Fi/Ethernet address
   a phone can reach and select **Save certificate**. The certificate is
   generated locally and is unique to this computer.
2. Install that certificate as trusted on the phone:
   - **iOS**: open the saved `.crt`, install the profile, then enable full trust
     in **Settings → General → About → Certificate Trust Settings**.
   - **Android development builds**: install it under **Settings → Security →
     Encryption & credentials → Install a certificate → CA certificate**. The
     debug build trusts the user certificate store.
   - **Android release builds**: Android does not trust user-installed CAs for
     apps by default. Use a device-management/enterprise system CA, or test with
     a development build. Certificate validation is never turned off.
3. On the desktop, select **Create pairing code**.
4. On the phone, open **Settings → Connections → Desktop computer** and scan the
   QR code, paste the pairing link, or enter the address and short code.
5. Approve the waiting phone on the desktop and choose the teammate that should
   answer its messages. The phone shows **Connected** when it has claimed its
   own key.

Both devices must be on the same network. If the phone cannot connect, allow
Ankita through the desktop firewall and keep the desktop awake.

## Managing a phone

- **Settings → Phone** lists paired phones with online state, assigned teammate
  and any active request. Disconnecting a phone cancels its active request and
  invalidates its key immediately.
- The phone can disconnect itself. It first asks the computer to revoke the key,
  then removes its local copy. If the computer is unreachable, the phone states
  that it was removed locally and the phone may still appear there.
- **Use desktop tools** on the phone switches delegation on or off without
  removing the pairing.

## Security model

| Control | Behavior |
| --- | --- |
| Invitation | 8 characters from an unambiguous alphabet, 2-minute lifetime, single use, 5 wrong guesses before it is burned |
| QR and link | Generated locally; contain the LAN address, short code, computer name and certificate fingerprint. They never contain the long-lived phone key |
| Phone key | 32 random bytes per phone; the phone keeps it in OS secure storage, the desktop stores only its SHA-256 hash |
| Transport | Local CA and leaf certificate, TLS 1.2+, certificate validation on, loopback addresses not advertised |
| Identity check | The phone compares the computer's certificate fingerprint with the code it scanned |
| Request ownership | Runs are bound to the authenticated device; another device receives 404, and revocation cancels that device's active run |
| Approvals | Tool approvals are forwarded to the phone and resolved through the desktop engine; cancellation still stops the real turn |
| Logs and metadata | Pairing content is not logged; only computer/teammate labels, device identity and the fingerprint are stored in ordinary app metadata |

Pending approval requests expire after two minutes, and at most three phones can
wait at once. The desktop shows the request and sends a notification if its
window is hidden.

## Verification

Automated checks use the real desktop `PhonePairing` service, a real HTTPS
socket and the real mobile pairing client. The Node test supplies the desktop
CA explicitly, which stands in for the phone's OS trust store.

| Check | Result |
| --- | --- |
| Desktop `test/desktop/phone-pairing.test.mjs` | 7/7 passed |
| Mobile `test/assistant-desktop-pairing.test.mjs` | 5/5 passed (strict links, metadata restore, wrong code, real claim/revoke, rejection, expiry) |
| Mobile full suite | 168/168 passed |
| `npm run desktop:build` | TypeScript passed; Vite built 395 modules |
| Desktop full serial suite (`node --test` over `test/`, concurrency 1) | 1514 passed, 0 failed, 1 skipped (1515 total); the skip is the POSIX permission test on Windows |
| Mobile `npm run typecheck` | passed (exit 0) |
| Mobile `npm run build:web` | passed; Expo bundled 559 modules into a 1.0 MB web bundle |
| Desktop `scripts/verify-desktop-phone-ui.mjs` | 5 grouped checks passed: narrow and wide invitations, expired code, pending/paired/revoked states, offline state, keyboard-only Settings navigation |
| Mobile `scripts/verify-desktop-pairing-ui.mjs` | 4 grouped checks passed: 390 px pairing and connected views, loopback/plain-HTTP rejection, 320 px layout without overflow, 44 px tap targets |

The two UI checks drive the real renderer and mobile web bundle in Chromium.
The desktop check feeds the real Settings component a stub `window.ankita`
surface and a locally generated QR data URL, because the verification machine
reported no LAN interface. Real Electron on that machine therefore showed the
honest offline state; the real HTTPS service, certificate and client round trip
are covered by the Node tests above, which supply the desktop CA explicitly in
place of a phone's trust store. The mobile web preview reports **Not reachable**
by design: its connected check goes through the local Ankita web relay, not the
native phone transport.

Not verified in this environment:

- No physical phone was used. The Android camera, OS certificate installation,
  mDNS/network discovery and a real LAN firewall were not exercised.
- No LAN address existed on the verification machine, so the packaged or
  development desktop never advertised a reachable invitation end to end.
- iOS certificate trust settings and background/teardown behavior on a phone
  were not exercised.
- Android release trust behavior: release builds keep the system trust store
  only, so a user-installed CA is not enough there. Development builds include
  a debug-only network security config that also trusts user CAs.
- The desktop was not packaged and paired from an installed build.
- The separate persistent-work service was not connected or tested.
