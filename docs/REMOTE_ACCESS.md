# Remote access from your Android phone

FRIDAY uses **Tailscale Serve**, which is reachable within your tailnet. Its Python server stays on `127.0.0.1`.
Remote access starts **OFF** on every backend restart. A detected Python source/dependency update also turns it off until restart and local enable.

## Set up Windows and Android

1. Install [Tailscale for Windows](https://tailscale.com/download/windows), sign in, and leave it running.
2. Install [Tailscale for Android](https://tailscale.com/download/android) on the phone. Sign in with the **same owner account**, then connect its VPN.
3. In the [Tailscale admin console](https://login.tailscale.com/admin/dns), enable MagicDNS and HTTPS certificates if prompted by Serve.
4. Restrict your tailnet policy so only your owner identity/devices can reach this laptop on HTTPS port 443. FRIDAY checks the owner identity again, and requires a locally approved device key.
5. Update FRIDAY's Python dependencies from its folder:

   ```powershell
   venv/Scripts/python.exe -m pip install -r requirements.txt
   ```

6. Start FRIDAY through its normal desktop launcher or `venv/Scripts/python.exe main.py --no-reload`.
7. At the **laptop**, say/type **enable remote**. Review the owner, tailnet and laptop DNS name in the native Yes/No prompt, then approve.
8. Say/type **pair my phone**. Scan the laptop QR with a compatible client, or use the test script below. The QR grant expires in 120 seconds and is consumed once.
9. Approve **Pair &lt;device name&gt;?** on the laptop. A token or key alone never activates a device.

No router port forwarding, public DNS service, public tunnel or Tailscale auth key is required.
Funnel must be off. If FRIDAY detects it, remote requests stop and a red warning appears. Say **disable remote** locally to run `tailscale serve reset` and clear Serve configuration; FRIDAY never enables or changes Funnel with a Funnel command.
Tagged/shared devices that cannot supply the saved owner login are refused.

## Try it before an Android app exists

At the laptop, enable remote, open the pairing QR, and click **Copy pairing JSON for the test script**. Then run:

```powershell
venv/Scripts/python.exe -B scripts/remote_sign_test.py --pair --local
```

Paste the copied JSON into the hidden prompt and approve the native pairing dialog.
The script verifies the server key against the QR fingerprint, pairs a software P-256 test key, and sends a signed status request.
Pairing and consent windows use Windows capture exclusion before revealing their contents. Copied setup JSON is marked private for clipboard history/cloud exclusion.
The default private test key lives at `memory/remote/test-phone.pem`, which is gitignored.
Protect that file with your Windows account permissions.

To exercise the actual Tailscale HTTPS path from a machine signed into the owner tailnet, omit `--local`:

```powershell
venv/Scripts/python.exe -B scripts/remote_sign_test.py --pair --url https://LAPTOP.TAILNET.ts.net
venv/Scripts/python.exe -B scripts/remote_sign_test.py --url https://LAPTOP.TAILNET.ts.net --command today_schedule
```

Each client machine needs its own pairing and key; copy only the short-lived QR JSON to the test client. Use `--key <local filename>` for a separate test device.
`--pair-json <filename>` can read locally saved QR JSON instead of hidden input; delete it after pairing.
`--args-json <filename>` supplies a JSON arguments object for commands that need one.
The script has no biometric approval credential, so sensitive commands are refused.
It never opens a listener or enables remote access.

## Owner controls

| Local command | Effect |
| --- | --- |
| `enable remote` | Owner confirmation, fresh safety checks, HTTPS Serve, enable latch |
| `disable remote` / `remote off` | Immediately close the gate, invalidate grants/challenges, reset Serve, notify |
| `remote status` | Check local Tailscale and remote state |
| `pair my phone` | Show a new one-use QR |
| `list paired devices` | Show names and IDs |
| `revoke <name>` | Revoke one exact name or ID immediately; use ID if names repeat |
| `show remote activity` | Show the last 20 local audit entries |

The tray has **Remote off**, also available through **Ctrl+Alt+Shift+R**. Windows reports if another application owns this shortcut.
Control Center → Live status shows enabled state, device count and the last successful command ID.
If Serve reset fails, the request gate remains off. The kill switch cannot undo effects already submitted to Windows or a messaging service.

## Allowed commands and limits

| Command IDs | Risk / arguments |
| --- | --- |
| `status`, `today_schedule`, `next_class`, `read_todos` | Safe; `{}` |
| `start_focus` | Safe; `{"minutes":25}` (1–1440) |
| `stop_focus` | Safe; `{}` |
| `set_scene` | Safe; `{"name":"quiet focus"}`; only locally approved scenes containing transient quiet/focus actions, with equally safe previous undo actions |
| `add_note` | Safe; `{"text":"Buy a charger"}`; fixed notes store |
| `ask_friday` | Safe conversation; `{"text":"Explain…"}`; usual provider/failover, no tools, command router, laptop history, phone notifications or audit data |
| `lock_pc`, `sleep_pc` | Confirmation required; `{}` |
| `open_app` | Confirmation required; `{"name":"chrome"}`; finite registered executables, no paths, arguments or command/script hosts |
| `send_message` | Confirmation required; `{"text":"…"}`; sends only to the existing configured owner Telegram chat |
| `delete_note`, `clear_notes` | Confirmation required; `{"number":1}` / `{}`; fixed notes store |

Unknown commands are refused. Shell/exec, files by path, installation, settings changes, pairing changes and disabling the kill switch are blocked.
Default scenes that open applications, URLs, files or music cannot run through the safe scene command. Approve/create an eligible quiet/focus scene locally first.
Remote-origin focus events, including later timer completion, cannot trigger automatic scene activation/undo.
Remote-origin bus events are delivered only to explicitly passive display subscriptions, so delayed mood/automation chains cannot acquire extra command authority.
Scene provenance survives timed exit, idle publication and plugin reload; an explicit local scene start establishes new local provenance.
Maximum 30 requests per minute per device. Five bad signatures lock that device for ten minutes and notify the laptop.

## Client protocol

Serve uses the locally verified CLI syntax:

```text
tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:8000/remote
```

Its external `/v1/...` requests map to internal `/remote/v1/...`. The QR contains the external HTTPS base URL and `signing_prefix=/remote`.
FRIDAY checks `tailscale status --json`, `serve status --json` and the read-only `funnel status --json`. CLI errors or unknown safety state cause refusal.
The actual process listener is checked as well as configured bind and request peer. Start with FRIDAY's launcher; proxy-header rewriting is disabled there.

Every request includes `X-Device-Id`, integer Unix-seconds `X-Timestamp`, random base64url `X-Nonce` (16–128 characters), and base64url `X-Signature`.
The ECDSA P-256/SHA-256 signed bytes are five UTF-8 lines, with **no final newline**:

```text
UPPERCASE_METHOD
/remote/v1/exact-path
lowercase_sha256_hex_of_exact_body_bytes
timestamp_header
nonce_header
```

Both Android DER and WebCrypto 64-byte P1363 signatures are accepted.
Timestamp skew must be at most 60 seconds; nonces cannot repeat for five minutes. Queries, ambiguous paths, duplicate auth headers and bodies above 16 KiB are refused.
Public keys are SPKI PEM. Device ID is the first 32 hex characters of SHA-256 of SPKI DER.

* `POST /v1/pair`: signed proof of the candidate key, body `{token,name,public_key}`; consume token, then ask the laptop. This enrolls a safe-only software test client.
* For biometric/PIN support, first `POST /v1/pair/begin` with the same fields. It consumes the grant and returns WebAuthn creation options (`userVerification=required`, platform, ES256). Create the credential, then `POST /v1/pair` with `{registration:<WebAuthn JSON>}` signed by the pending device key. Complete within 120 seconds and approve on the laptop.
* `GET /v1/pair/status` is signed by the pending/active key. Pairing responses include a server signature binding device ID, state and request nonce to the QR fingerprint.
* `GET /v1/status` and `POST /v1/commands` (`{command,args}`) require an active device.
* Confirming commands return `result=approval_required`, a random challenge ID, exact arguments and WebAuthn request options. After biometric/PIN verification, send a **new signed request** to `POST /v1/approve` with `{challenge,approval:<WebAuthn JSON>}` within 60 seconds.

The server validates the WebAuthn RP/origin against this laptop's HTTPS MagicDNS name, checks user presence and user verification, and consumes the command-bound challenge once. Kill/revoke/expiry invalidate approval.
App targets, message recipient configuration and notes revisions are rechecked before submission; changed targets require a new approval.
A client-supplied `biometric=true` flag or a plain device signature cannot approve a sensitive action.
WebCrypto request keys work in browsers; a native Android client should generate its request key in Android Keystore. This server does not claim or verify hardware attestation of that request key.
WebAuthn approval requires a compliant client/authenticator; no Android app or browser UI is shipped in this change.

## Local storage and validation

`memory/remote/devices.json` stores public keys, names, timestamps, scopes and optional public WebAuthn credential/counter data.
`setup.json` contains the owner login and MagicDNS name; `server-key.pem` is the laptop's private pairing identity.
`audit.jsonl` records time, device ID, allowlisted command ID, risk, outcome and validated tailnet source IP. It contains no chat/notification text, token, signature or request body. It rotates at 5 MiB, retaining one previous file.
Audit and pairing/device data do not enter model prompts. Only the explicit `ask_friday` question reaches the configured conversation provider.

Tests under `tests/remote` mock the CLI and OS/provider effects, using in-process HTTP. See `tasks/remote/focused.xml` and `full.xml` for local validation receipts when available.
The transport is default-off; this change does not enable Serve or enroll a real device during development.

References: [Tailscale Serve and identity headers](https://tailscale.com/docs/features/tailscale-serve), [Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve), [python-fido2 server](https://developers.yubico.com/python-fido2/API_Documentation/autoapi/fido2/server/index.html).

## Files changed

* New server package: `services/remote/{__init__,context,security,tailscale,pairing,approval,commands,handlers,conversation,service,routes,local,desktop,audit}.py`.
* Existing bridge/pipeline: `interfaces/api/app.py`, `interfaces/api/routes/{chat,voice,system}.py`, `main.py`, `services/mind/cognition.py`.
* Event/feature safety: `services/event_bus.py`, `services/friday_island_server/http.py`, `plugins/focus/timer.py`, `plugins/scenes/{engine,triggers}.py`, `services/memory/notes.py`.
* Desktop controls/status: `interfaces/tray/{app,backend,tray}.py`, `interfaces/popup/{app,win32}.py`, `interfaces/control_center/app.py`.
* Client/dependencies: `scripts/remote_sign_test.py`, `requirements.txt`.
* Tests: `tests/remote/{conftest,test_security,test_pairing_lifecycle,test_approval_pipeline,test_registration_and_events,test_tailscale_cli}.py`; updated hotkey stub in `tests/test_desktop_integration.py` and initialization wait in `tests/test_scene_plugin_lifecycle.py`.
* Documentation: this guide, `docs/architecture.md`, `docs/decisions.md`. Local policy/test/source receipts are under ignored `tasks/remote/`.

Existing independent briefing changes in this checkout are preserved.
