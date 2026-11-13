# FRIDAY on your phone

The phone panel reuses the P0 Tailscale owner gate. It has no public internet endpoint. All API requests use your phone's non-extractable P-256 key; the cached shell can open offline but cannot run commands offline.

## Build and install

1. On the laptop, build the local assets once:
   ```powershell
   cd island
   npm run build:remote
   ```
   The generated `island/remote-dist/` is served by FRIDAY. No separate web server is needed. Rebuild after editing `island/remote/`.
2. Restart FRIDAY after this source update. Say **enable remote** and approve the laptop prompt. P0 intentionally disables remote access after updates and every restart.
3. Connect the phone to the same Tailscale account/tailnet owner identity as the laptop. In the phone browser open **https://YOUR-LAPTOP.YOUR-TAILNET.ts.net/app/**.
   The bridge route is `/remote/app/`. P0's existing Serve configuration proxies public `/` to bridge `/remote`, so the public phone URL is `/app/`. Do not duplicate the `/remote` prefix on the Tailscale URL. HTTPS is required for real phone cryptography, camera, service worker and installation.
4. Say **pair my phone** on the laptop. Scan its QR using the phone panel, or copy/paste the **whole QR JSON** into Pairing code. Give the phone a name and set a six-digit approval PIN. Submit, then approve the pairing prompt **on the laptop** within 120 seconds. The panel verifies the laptop fingerprint and signed response before accepting pairing.
5. Install: in Chrome on Android, open the browser menu and choose **Add to Home screen / Install app**. On iPhone Safari, choose **Share → Add to Home Screen**. Open the installed FRIDAY icon. If your browser keeps installed-app storage separate, pair inside that installed app.

The shell, icons and fonts are entirely local. The private signing key stays non-extractable in IndexedDB. Clearing browser/site data removes that key; pair again and revoke the old device on the laptop. Never paste pairing data into chat or share it elsewhere.

## Controls

- **Home:** battery, current application (privacy-filtered identity only), active scene, next class/faculty, due-today count, focus remaining, Mochi mood. Missing services show unavailable values independently.
- **Chat:** signed fetch stream through the allowlisted `ask` capability and the existing isolated provider/failover conversation pipeline, with `remote_request` enabled. No remote text enters chat history, audit text, events or automatic tool routing. Current providers return a complete reply; the stream sends keepalives then that reply, rather than individual provider tokens.
- **Voice:** hold to talk, release to send. Keyboard Space/Enter also work. Browsers without SpeechRecognition show a typing fallback. Recognition is handled by the browser and may use its speech service; FRIDAY adds no server transcription. Spoken replies are optional.
- **Quick actions:** focus 25, study/exam/game/sleep scenes, lock PC. Scene safety still follows P0: only locally approved scenes containing transient focus/quiet-mode effects can execute remotely; other scenes require local review. No arbitrary application or shell execution is added.
- **Schedule:** today, tomorrow, assignments and exams, read-only, using laptop-local dates and effective schedule corrections.
- **Activity:** last 20 metadata-only audit entries. **Devices:** this phone's saved name and self-revocation. A failed revoke preserves the key so you can retry; revoke from the laptop if the phone is lost.

Locking the PC uses an expiring challenge and your PIN. Challenges are single-use and bind the device, command, arguments, target and enable epoch. After three incorrect PINs, approvals for that device lock for ten minutes; restarting FRIDAY does not clear this lockout. Request a new challenge after a failed attempt. New HTTP pairings require a PIN; existing P0 devices remain compatible. The existing P0 WebAuthn implementation is retained; this PWA currently uses PIN approval rather than enrolling a platform authenticator.

Status/schedule/events/activity/device and chat all have explicit safe registry capabilities. The events fetch stream reconnects with fresh signatures, projects only selected fields, forwards mood/schedule changes and public FRIDAY notifications, and emits live focus ticks. Streams stop on kill/revocation and rotate after about 25 seconds; transient disconnects back off, with a 35-second watchdog for stalled networks. Events are live, without replay guarantees across disconnects.

## Offline and troubleshooting

After the first successful shell install, opening the app offline shows **Laptop unreachable** and the saved status age. Commands and messages are never queued. Only the latest status is persisted; chat and schedule pages are not cached. The shell cache never handles signed requests or API paths.

If access fails, check Tailscale connectivity, laptop wake state, owner identity, enabled remote status, and the phone clock (P0 permits at most 60 seconds skew). P0 gives generic refusal responses, so an unavailable laptop and a security refusal may look the same. If a PIN is locked, wait ten minutes. Use the local **remote off** kill switch at any time.

## Validation

```powershell
cd island
npm test
npm run build
npm run build:remote
cd ..
venv/Scripts/python.exe -B -m pytest tests/remote -q -p no:cacheprovider
venv/Scripts/python.exe -B -m pytest tests -q -p no:cacheprovider
```

Shared protocol vectors are in `tests/remote_vectors.json`. Python and JavaScript verify canonical UTF-8 bytes and P1363 signatures. The Playwright pytest smoke uses a local mocked API that verifies actual browser signatures, exercises pairing, restored non-extractable keys, chat, confirmation, schedule, audit, rejected/successful revocation and offline reload at 360 px. It writes screenshots to `tasks/remote-pwa/`. It skips only if Playwright/Chromium is unavailable. Real phone installation, camera recognition, speech recognition and laptop lock effects still need a device check.

Validated on 2026-11-13: **36 JavaScript tests passed**, both builds passed, and **npm audit reported zero vulnerabilities**. Full Python coverage reconciled to **7,155 unique cases passed, 13 skipped, zero unresolved failures**. The first four-process run had 28 remote-fixture discovery errors and one desktop transport readiness timeout. The normal remote-directory rerun passed all **102** tests, including Playwright; the readiness test passed alone. These are recorded as retries, not an uninterrupted green full run. Exact source hashes remained unchanged. Receipts, raw XML/logs and five 360px screenshots are under `tasks/remote-pwa/` (local, gitignored).

The broad Ruflo scanner reported 28 high and 35 medium pattern findings across the repository, including third-party `venv` content and existing files. Its finding in the new bundle is the reused fixed Mochi SVG `innerHTML`; remote response data uses `textContent`. Read-only security review found no blocking issue in this change. The scanner does not replace the Python gate/PIN tests or dependency audit.

## Files changed

40 files, including eight generated shell assets:

| Area | Files |
| --- | --- |
| Remote backend | `services/remote/app_shell.py`, `approval.py`, `commands.py`, `pairing.py`, `panel.py`, `pin.py`, `routes.py`, `service.py`, `streams.py` |
| Phone source | `island/remote/app.mjs`, `index.html`, `pairing.mjs`, `signing.mjs`, `style.css`, `transport.mjs`, `voice.mjs` |
| Local install assets | `island/remote/public/manifest.webmanifest`, `sw.js`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png` |
| Generated served shell | `island/remote-dist/app.js`, `style.css`, `index.html`, `manifest.webmanifest`, `sw.js`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png` |
| Build | `island/package.json`, `island/vite.remote.config.ts` |
| Tests | `island/tests/remote-signing.test.ts`, `tests/remote_vectors.json`, `tests/remote/test_panel.py`, `test_pwa_browser.py`, `test_pairing_lifecycle.py`, `test_registration_and_events.py` |
| Software pairing client | `scripts/remote_sign_test.py` (new mandatory PIN prompt) |
| Documentation | `docs/REMOTE-PWA.md`, `docs/specs/2026-11-13-remote-pwa.md` |
