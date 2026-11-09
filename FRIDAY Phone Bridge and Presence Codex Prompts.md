# FRIDAY Phone Bridge and Presence: Codex Prompts

Nov 6, 2026 · @Chaitanya

## How to use this doc

Seven Codex prompts (P0 to P6) connect your Android phone to FRIDAY over Tailscale, let her learn from what you do on both devices, and add presence and self-care on top. Run one prompt per Codex session, in order, and test on your real phone before moving on. Everything else we discussed (brain tracks, voice, life graph, math and study tools, stories and jokes, lecture recorder, gestures and hardware) is further down, starting at "Everything else we discussed".

Every prompt starts by making Codex read your repo, because FRIDAY already has an event bus, a plugin manager, a token-protected localhost bridge (`interfaces/api`), `services/activity`, `services/phone` (KDE Connect) and the mind modules. The prompts extend those. They do not add a parallel system.

### The decisions behind the prompts

- **Tailscale, never public.** FRIDAY keeps listening on `127.0.0.1` only. `tailscale serve` publishes it to your tailnet over HTTPS. Tailscale Funnel (public internet) must never be turned on.
- **Android only.** Only Android lets an app see the foreground app and screen time, so the companion is a native Kotlin app. Control from the phone also works from a PWA in Chrome.
- **Works with no LLM.** Every feature is rule-based or statistical. An LLM can polish wording, and nothing waits on it.
- **The phone never gets a shell.** It can send only allowlisted commands. Risky ones need a PIN or biometric on the phone.
- **Phone data stays on the laptop.** No raw phone data goes to any LLM or cloud. Each signal has its own switch, a retention limit, and a "forget phone data" command.
- **She learns, you confirm.** Anything FRIDAY infers about you from the phone is a proposal until you accept it, the same rule your mind modules already follow.

&#91;embedded content: architecture · phone, Tailscale tunnel, laptop\]

Every phone request passes the P0 gate first. The phone never reaches the core directly, and laptop-to-phone messages travel back through the same tunnel.

### Order

1. **P0 Secure bridge:** Tailscale-only access, QR pairing, per-device keys, allowlist, audit log, kill switch.
2. **P1 Phone PWA:** control panel, chat, push-to-talk, status card.
3. **P2 Android companion:** collects phone signals with per-signal toggles.
4. **P3 Cross-device timeline and learning:** one timeline for laptop and phone.
5. **P4 Handoff and sync:** clipboard, files, find my phone, offline queue, phone as second factor.
6. **P5 Presence and triage:** places trigger scenes, notifications get ranked.
7. **P6 Self-care and coaching:** phone-use nudges (ask first), wellbeing, goal coaching.

P0 must come first, because everything else rides on its security.

## P0: Secure bridge over Tailscale

This prompt builds the locked front door: your phone can reach FRIDAY from anywhere, and nobody else can. You pair the phone once with a QR code. Every request is signed by that phone's own key, and the phone can run only the commands on an allowlist.

**Do this yourself first:** install Tailscale on the laptop and on the phone, sign in to the same account on both, and check that the phone can ping the laptop's name in the Tailscale app. Do not turn on Funnel.

```text
You are working in the FRIDAY repo (Windows, Python). Goal: let a paired Android phone reach FRIDAY remotely and safely over Tailscale. Nothing may be exposed to the public internet.

STEP 0 - READ FIRST (no edits yet)
Read: docs/architecture.md, docs/decisions.md, core/config.py, interfaces/api (the localhost bridge: X-Friday-Token auth, Host/Origin checks, SSE /api/events), services/automation/intent.py (the remote_request context var), services/phone/*, the plugin manager, services/settings_store, and how the Telegram bot gates commands if it exists. Write a 15-line summary: how a remote command is authorised today, what remote_request changes, and where a new transport should hook in. Then continue.

BUILD
1. New package services/remote/. Mount a /remote/v1 route group on the EXISTING bridge. Do not start a second server. FRIDAY stays bound to 127.0.0.1. Add a startup assertion: if the server is bound to any non-loopback address, the remote routes refuse to register and a warning is shown.

2. services/remote/tailscale.py
   - Detect the tailscale CLI. Use `tailscale status --json` for: installed, logged in, tailnet name, this machine's MagicDNS name, serve status.
   - Command "enable remote" (owner confirms first) runs `tailscale serve --bg https / http://127.0.0.1:<port>/remote` (check the current CLI syntax with `tailscale serve --help` and use what it says). Command "disable remote" runs `tailscale serve reset`.
   - Check `tailscale funnel status`. If Funnel is on: show a red warning, reject all remote requests, offer to turn it off. Never run `tailscale funnel` yourself.
   - Request gate. Accept a remote request only if (a) the Host header is the MagicDNS name or localhost, (b) the Tailscale-User-Login header matches the owner login saved at setup, (c) the device signature is valid (step 3). Anything else gets a generic 404 and an audit entry.

3. services/remote/pairing.py
   - "pair my phone" shows a QR containing: tailnet URL, a one-time token valid 120 seconds, laptop name, and the server key fingerprint. The token works once.
   - The phone generates an ECDSA P-256 keypair (hardware-backed on Android, and WebCrypto in a browser supports it too) and sends its public key, device name and the token. FRIDAY asks on the laptop ("Pair <name>? yes/no") and activates the device only after yes. Store devices in memory/remote/devices.json: id, name, public key, created, last_seen, scopes.
   - Every request carries X-Device-Id, X-Timestamp, X-Nonce, X-Signature (over method + path + sha256(body) + timestamp + nonce). Reject timestamp skew over 60 s and any nonce seen in the last 5 minutes. Use the cryptography library (add to requirements).
   - Commands: "list paired devices", "revoke <name>". Revoked devices are rejected immediately.

4. services/remote/commands.py - the allowlist
   - A registry: command id -> handler + risk level (safe | confirm | blocked).
   - safe: status, today's schedule, next class, start/stop focus, set scene, read todos, add a note, ask FRIDAY (goes through the normal pipeline with remote_request set).
   - confirm (needs a fresh signed approval from the phone's biometric/PIN within 60 s): lock PC, sleep PC, open an app, send a message, anything that deletes or sends. Build the server side: return a challenge, accept a signed approval.
   - blocked, always: shell/exec, reading or writing files by path, installing anything, changing settings, changing pairing, disabling the kill switch.
   - Unknown command = refused. Add a test that fails if a handler is registered without a risk level.

5. Audit log: memory/remote/audit.jsonl. One line per request: time, device, command, risk, result, tailnet source IP. Never store chat text or notification text. Command "show remote activity" lists the last 20. Rotate at 5 MB.

6. Kill switch: "remote off" command, a tray menu item and a global hotkey (check existing hotkeys for conflicts and pick a free one) disable the /remote routes at once, run `tailscale serve reset` and notify. Remote is OFF by default on a fresh install and after every update. The owner must enable it.

7. Rate limits: 30 requests/min per device; 5 bad signatures locks that device for 10 minutes and notifies me.

8. If the island or control center has an obvious spot, add a read-only remote status (enabled, number of devices, last remote command).

TESTS (pytest, no real network, mock the tailscale CLI)
Signature accept/reject, replay rejection, skew rejection, used/expired pairing token, non-loopback bind refusal, Funnel-on refusal, unknown command refusal, risk-level registration test, revoke, kill switch, audit rotation. Run the whole existing suite; nothing existing may break.

DO NOT: bind to a non-loopback address; add ngrok; add any shell or exec passthrough; store a Tailscale auth key; send audit or phone data to any model; change existing Telegram behaviour.

DELIVER: files changed; plain-language steps for me to set up Tailscale on Windows and the phone; scripts/remote_sign_test.py that sends a signed test request so I can try pairing without the app; what is left.
```

## P1: Phone control panel (PWA)

This prompt builds FRIDAY's phone face: an installable web app in the same amber-and-dark style as the island, with a status card, chat, push-to-talk voice, quick actions and your schedule. It needs no app store and works with the P0 pairing, so you can control FRIDAY from the phone before the Android app exists.

**Do this yourself after it is built:** open the laptop's Tailscale address in Chrome on the phone, pair with the QR code, then choose Add to Home screen.

```text
You are working in the FRIDAY repo. P0 (services/remote: Tailscale gate, QR pairing, signed requests, allowlist, audit, kill switch) is done. Goal: a phone control panel served by FRIDAY as an installable PWA.

STEP 0 - READ FIRST (no edits yet)
Read services/remote/* (the signing format, pairing flow, command registry, confirm challenge), the island front-end (island/) for design tokens and the Mochi character, the college schedule API, the SSE event stream in interfaces/api, and how the control center builds its status. Write a 10-line summary of what you will reuse. Check whether the island uses a bundler; if so, reuse it, otherwise use plain JS with no build step.

BUILD
1. PWA served at /remote/app/ through the same P0 gate (Tailscale identity check, then signed API calls). Files: index, manifest.webmanifest, icons, service worker that caches the app shell so it opens instantly. All assets bundled locally: no CDNs, no external fonts. Dark glass style with the amber #FFB347 glow, small Mochi character, large touch targets, works at 360 px wide.

2. Pairing screen: scan the QR with the BarcodeDetector API where available, plus a paste-the-code fallback. Generate a NON-EXTRACTABLE ECDSA P-256 key with WebCrypto, store it in IndexedDB, sign requests exactly as P0 specifies. Create shared test vectors (tests/remote_vectors.json) so Python and JS agree on the canonical string to sign.

3. Screens
   - Home: status card (laptop reachable, battery, current app and scene, next class with faculty name, due today, focus timer, Mochi mood).
   - Chat: text chat with FRIDAY through the allowlisted "ask" command (normal pipeline, remote_request set). Stream the reply with a signed fetch stream, because EventSource cannot send custom headers.
   - Voice: push-to-talk using the browser SpeechRecognition API (no server speech-to-text needed), sends the text through chat; optional spoken reply with speechSynthesis. Show a clear message if the browser lacks support.
   - Quick actions grid: focus 25, scenes (study, exam, game, sleep), lock PC (confirm), and room for more.
   - Schedule: read-only today, tomorrow, assignments, exams.
   - Remote activity: last 20 audit entries. Devices: this phone's name, revoke.

4. Confirm flow: for confirm-risk commands show the challenge screen. Mandatory: a 6-digit PIN set at pairing, stored on the laptop hashed (scrypt), 3 tries then 10 minute lockout. Optional if the library is simple: WebAuthn platform authenticator (fingerprint) as the approval.

5. New endpoints under /remote/v1: status, schedule, events (signed fetch-stream with auto-reconnect; forwards mood.changed, schedule alerts, focus ticks, FRIDAY notices). Each must go through the allowlist with a risk level.

6. If the laptop is unreachable, show "laptop unreachable" plus the last known status with its age. Do not queue commands yet (that is P4).

TESTS
Python: the new endpoints, the gate, the allowlist. JS: signing matches the shared vectors. If the repo has Playwright, add a smoke test of the PWA against a mocked API. Run the full existing suite.

DO NOT: make keys exportable; use third-party CDNs; log chat text; add any endpoint that is not on the allowlist.

DELIVER: files changed; steps for me to install the PWA on my phone; screenshots at 360 px if Playwright is available; what is left.
```

## P2: Android companion app

This prompt builds a small native Android app that tells FRIDAY what your phone is doing: which app is in front, whether the screen is on, battery, Wi-Fi, walking or sitting, and arriving at or leaving places you name. Every signal starts switched off, has its own explanation before Android asks for the permission, and can be paused or wiped from the phone. The laptop side stores it in its own phone database.

**Do this yourself:** install Android Studio on the laptop (Codex writes the code, you press Build), and build a debug APK to install on your phone. Android will ask you to allow installs from your own file manager.

```text
You are working in the FRIDAY repo. P0 (services/remote) and P1 (PWA) are done. Goal: a native Android companion app (Kotlin) plus the laptop-side receiver for the phone's signals.

STEP 0 - READ FIRST (no edits yet)
Read services/remote/* (signing, device scopes, allowlist), tests/remote_vectors.json, services/activity/* (how laptop activity is logged and categorised), services/phone/* and the event bus. Summarise in 15 lines: the event shapes the activity log uses, where phone events should plug in, and how device scopes work. Check whether an Android SDK exists on this machine. If it does not, write the project so it builds in Android Studio and do not try to build it here; keep logic in plain Kotlin classes that can be unit-tested on the JVM.

BUILD - ANDROID APP (folder android/, Kotlin, Jetpack Compose, Gradle wrapper, current stable AGP, minSdk 29, targetSdk current)
1. Pairing: scan the P0 QR (CameraX + ML Kit barcode scanning, with a paste-code fallback). Generate an ECDSA P-256 key in the Android Keystore (StrongBox when available, never exportable). Sign requests exactly as P0 specifies; a JVM unit test must pass the shared vectors in tests/remote_vectors.json. OkHttp, HTTPS only, no cleartext traffic, base URL from the QR.

2. A foreground service with a quiet persistent notification ("FRIDAY connected - sharing: app, screen"). WorkManager for periodic sync. Events are saved to a Room database first (cap 7 days or 5000 events) and sent in batches every 5 minutes, or at once for important events, and kept when the laptop is unreachable. Ask for a battery-optimisation exemption with an explanation, not silently.

3. Signals. Each one is a separate toggle, OFF by default. Each has an explanation screen shown BEFORE its permission is requested. Never ask for a permission before the toggle is turned on.
   - app_usage: UsageStatsManager (Usage Access special permission). Foreground app changes while the screen is on (poll about every 15 s). Send package, label, Android app category, start and end time.
   - screen: screen on/off and unlock count.
   - battery: level, charging state.
   - network: Wi-Fi vs mobile; the home Wi-Fi is recognised by a salted hash of the SSID, never the name.
   - motion: Play Services activity recognition transitions (still, walking, in vehicle).
   - places: geofences for places I name on the phone (home, college, library). Send only "entered X" and "left X". Coordinates never leave the phone.
   - audio devices: headphones or Bluetooth audio connected, with the device label.
   - media: now-playing app, title and artist via a notification listener (optional, default off).
   - notifications: package, time and category only. No title and no text. A per-app "allow content" list exists, empty by default.
   - sleep and steps: Health Connect, read-only daily aggregates.
   - interruption mode: Do Not Disturb or ringer state.

4. Phone-side controls: per-signal toggles; "pause everything for 1 hour"; a "Sharing now" screen listing exactly what was sent in the last hour; retention setting; "Forget phone data" which wipes the phone buffer AND calls the laptop to delete everything stored from this phone; a button that opens the PWA in a Chrome Custom Tab.

BUILD - LAPTOP SIDE
5. POST /remote/v1/phone/events accepts a batch (event id, timestamp, type, payload). It needs a device scope "phone_data" (add scopes to devices.json if P0 did not). Validate against a strict schema per type; reject unknown types, oversized payloads, and any payload with notification title or text fields. Deduplicate by event id. Store in memory/phone/phone_events.db (SQLite) with a retention default of 30 days. Publish a bus event phone.event for each stored event (type and time only). Add a heartbeat endpoint (battery, app version, last sync).

6. Add allowlisted commands: "phone status" (last heartbeat, which signals are on), "forget phone data" (confirm risk). Do not touch the KDE Connect code in services/phone; this is a separate, additive path.

TESTS
Python: schema rejection, dedupe, scope check, retention purge, text-field rejection, forget-data. Kotlin JVM tests: signing vectors, the Room buffer, the batch sender against a fake server, toggle-off means no collection. Run the whole existing Python suite.

DO NOT collect: keystrokes, screen contents, accessibility-service data, SMS, call logs, contacts, photos, microphone audio, raw GPS. Do not use Firebase, analytics, ads or any third-party server. Do not send notification text by default. Do not use a Google account login.

DELIVER: files changed; android/README with plain-language build and install steps for Android Studio and a debug APK; a table of every permission and why it is needed; what is left.
```

## P3: One timeline and learning from the phone

This prompt gives FRIDAY one picture of your day across laptop and phone, and lets her notice patterns in it. She can tell which device has your attention, answer "what am I using on my phone", and spot habits like "phone apps right after study blocks". She learns with counts and probabilities, not an LLM, and each pattern she finds is a question for you. It is never stated as a fact until you confirm it.

```text
You are working in the FRIDAY repo. P0 to P2 are done: phone events arrive in memory/phone/phone_events.db and on the bus as phone.event. Goal: merge them with laptop activity and let the mind learn from them, with no LLM needed.

STEP 0 - READ FIRST (no edits yet)
Read services/activity/* (log, categories), services/mind/learner.py, app_learning.py, knowledge.py, thoughts.py, temporal_memory.py, life_state.py, humour.py (situation()), reflection/consolidation, wording.py, how the morning and night briefings collect data, and services/phone/commands.py for the command-matcher style. Summarise in 15 lines how an observation becomes a thought, then a question, then a stored reason, and where the phone data should join that path.

BUILD
1. services/activity/timeline.py: merge the laptop activity log and phone app_usage events into segments (device, app, category, start, end). Extend the categoriser for Android: use the Android app category and a package-name table first. Unknown packages go through the EXISTING unknown-app flow (local rules first, the LLM only as an optional teacher, the owner confirms) - reuse knowledge.py, do not write a second one.

2. where_is_attention(now) -> laptop | phone | both | away, with confidence and a plain reason. Rules: phone screen on + unlocked + motion = phone in use; laptop input idle for N minutes while the phone screen is on = attention on phone; charging overnight + screen off = asleep. Publish attention.changed on the bus when it flips (debounced so it does not flap).

3. services/mind/phone_patterns.py (rule-based and statistical, in the style of humour.py and learner.py):
   - cross-device next-app prediction: extend the existing predictor with phone apps (features: hour, weekday, place, previous app, device);
   - distraction pattern: phone-app time inside study, class or deadline windows (reuse humour.situation and personality study/class checks);
   - sleep and wake estimate from first unlock, last screen off, night charging; compare with Health Connect sleep when present;
   - place routines (home to college times) as frequency tables with half-life decay.
   Each finding becomes a thought via thoughts.add (new kind "phone_pattern", raw data only, strength from surprise, the existing repeat guard). It goes through the existing evening-question flow, and the answer is stored as the reason for that pattern. Nothing is treated as true until the owner confirms.

4. Offline commands (matchers in the services/phone/commands.py style, answers built from raw data through wording.plain()): "what am I using on my phone", "how long was I on <app> today", "which device have I used more today", "when did I last use my phone", "what did I do after class". These work with the LLM off. If the LLM wording path is used, pass only categories and durations, never app names, unless I turn that on in settings.

5. Hook into what exists: add a phone line to the morning and night briefings (screen time, top category, first unlock time); give life_state a phone-attention input; add GET /remote/v1/timeline (allowlisted, safe) and a simple Timeline screen in the PWA with two lanes (laptop, phone) for today.

6. Privacy: phone data is excluded from semantic search indexes and AI context by default. "Forget phone data" must cascade: delete derived phone_pattern thoughts and phone-derived learner state, then retrain on what remains.

TESTS
Synthetic day fixtures with laptop and phone segments; attention resolution cases including flapping; pattern detection with known answers; the owner-confirm flow; the command matchers; the forget cascade; everything with the LLM disabled. Run the full suite.

DO NOT: send app names to any model by default; state an inferred habit as fact; add any LLM dependency; change how existing laptop-only learning behaves.

DELIVER: files changed; a one-page description of each pattern and how it can be wrong; what is left.
```

## P4: Handoff, sync and two-way control

This prompt makes the connection run both ways. You can share a link or a file from the phone to the laptop, send things the other way, make either device ring so you can find it, and keep working when the laptop is asleep (safe commands wait in a queue). The phone also becomes a second factor: when FRIDAY is about to do something risky on the laptop, she asks for your fingerprint on the phone.

Android blocks background clipboard reading, so clipboard and handoff from the phone use the Share menu ("Share to FRIDAY") and a Quick Settings tile. There is no silent clipboard watching.

```text
You are working in the FRIDAY repo. P0 to P3 are done. Goal: two-way handoff, sync, find-my-device, an offline queue and phone approvals.

STEP 0 - READ FIRST (no edits yet)
Read services/remote/*, the Android app in android/, the smart clipboard plugin (history store, secret/sensitive detection), the semantic file search, how FRIDAY currently asks the owner to confirm risky actions on the laptop, and the plugin API. Summarise in 15 lines how a laptop-side confirm prompt works today and where a phone approval can plug in.

BUILD - TRANSPORT
1. Laptop-to-phone channel without Firebase: the Android foreground service keeps a signed long-poll on /remote/v1/phone/inbox (30 s timeout, auto-reconnect with backoff). The laptop puts messages in a per-device outbox in SQLite (id, type, payload, created, expires_at, delivered). Message types below.
2. Offline queue (phone to laptop): when the laptop is unreachable, the PWA and the Android app queue ONLY safe-risk commands, each with an expiry (default 15 minutes, max 24 hours) and a visible "waiting" state. Confirm-risk commands are never queued. When the laptop is back, the queue is sent oldest first, with ids so nothing runs twice. The same expiry rules apply to the laptop outbox.

BUILD - FEATURES
3. Handoff to laptop: Android Share target "Share to FRIDAY" for text, links and files. Links open on the laptop only if the scheme is http or https (safe risk); other text goes to the smart clipboard history as source=phone. FRIDAY asks "open this link now?" only when the laptop is in focus or study mode.
4. Handoff to phone: "send this to my phone" (current browser URL, current clipboard item, a note, a file) puts a message in the outbox. The phone shows a notification with an Open action.
5. File sync: phone-to-laptop files land in a quarantine folder (default Documents/FRIDAY-from-phone/). Cap 100 MB per file. Refuse executable and script extensions (exe, bat, cmd, ps1, msi, scr, lnk, vbs, js, jar, dll and similar). Compute sha256, add an audit entry, never auto-open. Laptop-to-phone files go to the phone's Downloads/FRIDAY. Add the quarantine folder to semantic file search only if I turn that on.
6. Clipboard: Android Quick Settings tile and a share action push the current clipboard to the laptop. Laptop to phone happens only on "send to phone". No automatic two-way clipboard sync by default. A setting can enable laptop-to-phone auto-sync, which always runs the existing secret detection first and skips anything that looks sensitive.
7. Find my phone: "ring my phone" plays on the ALARM audio stream at full volume even on silent, shows a Stop button, and also reports last known place, battery and last seen. Find my laptop: from the phone or PWA, "ring my laptop" plays a loud sound and shows a toast (safe risk) and reports its last active app and idle time.
8. Phone as second factor: add approvals.request(action, summary, timeout=60) on the laptop. It puts an approval message in the outbox; the phone shows a high-priority notification, then the Android BiometricPrompt guarding a Keystore key that requires user authentication; the signed result returns to the laptop. Wire it as an OPTIONAL second factor to the existing laptop confirm prompts for deleting files, sending messages and settings changes, behind a setting. It must never be used to unlock Windows, and the laptop prompt stays available as the fallback if the phone is unreachable.

TESTS
Outbox expiry and delivery; queue ordering and no double-run; confirm-risk never queued; link scheme filter; blocked file extensions; quarantine path traversal (../ and absolute paths rejected); size cap; approval accept, deny and timeout; replayed approval rejected. Kotlin JVM tests for the queue and signing. Run the full suite.

DO NOT: read the clipboard in the background; auto-open or auto-run anything received; accept file paths from the phone; auto-sync sensitive clipboard items; weaken any P0 rule.

DELIVER: files changed; how to test each feature with the phone; what is left.
```

## P5: Presence, place-based scenes and notification triage

This prompt gives FRIDAY a sense of where you are and what mode you are in, across both devices, and lets that start things. Reaching college during a class window can switch on class mode, and leaving home can trigger a "what do I need today" check. Her phone notification sorting learns from what you actually open. New automations start in ask-first mode and earn the right to run on their own.

```text
You are working in the FRIDAY repo. P0 to P4 are done: phone signals (places, motion, screen, charging), where_is_attention(), the scenes plugin, the schedule API and the outbox to the phone exist. Goal: presence, place-triggered scenes with a trust ladder, anticipation, and notification triage.

STEP 0 - READ FIRST (no edits yet)
Read the scenes plugin, services/mind/life_state.py, the nudge and quiet-time budgets and the executive review loop in services/mind, humour.py (Beta beliefs), the schedule/timetable service, the notification-related code in services/phone (KDE Connect; its rule that notification content never enters AI or history must stay), and the P2 notification-metadata signal. Summarise in 15 lines how an automatic action is currently allowed, budgeted and silenced.

BUILD
1. services/presence/engine.py: combine place, motion, charging, screen state, laptop idle, time and the timetable into one state: at_desk, on_phone, in_class, commuting, at_college_free, at_home, away, winding_down, asleep. Rule-based, with hysteresis and minimum dwell times so it does not flap. Publish presence.changed with the state, the reason and the confidence. Expose "where am I / what mode am I in" as an offline command. Show the state on the PWA home screen, and as a small phone icon with the state on the island.

2. Place-based scenes: add a "presence" trigger type to the scenes plugin: trigger (arrive/leave place, enter/leave state) + conditions (weekday, time window, in a class window) + actions (start a scene, show a card, send a phone notification, set phone Do Not Disturb or ringer mode through the companion if I granted that access, read out what is due today). Rules are stored as JSON and can be created by a simple offline grammar: "when I reach college start class mode", "when I leave home tell me what is due today", "at 11 pm start sleep mode". Show the parsed rule back and ask me to confirm before saving.

3. Trust ladder: every new rule starts at level ask (FRIDAY asks "you reached college - start class mode?"). After 3 accepts in a row she offers once to move it to level do-and-tell. One undo or one "no" moves it back down a level. Store the ladder per rule. Risky actions (anything on the P0 confirm list) never go above ask. Every automatic run is logged and can be undone with "undo that".

4. Anticipation: use the learned commute times (P3) plus the timetable to say things like "leave in 10 minutes for your 9:00 class", "your lab record is due tomorrow and you are at home with nothing planned", or "you usually start studying around now". These go through the EXISTING nudge budgets, quiet hours and executive review loop. They must be rule-based, must say why they fired, and must never be sent while in study, exam or sleep scenes unless urgent.

5. Notification triage: score each phone notification from app importance, situation (study, class, sleep, free) and what you did with similar ones. Learn from what you do: the companion's notification listener reports whether a notification was opened or dismissed (removal reason). Keep a Beta belief per app and situation, like humour.py, with nightly decay. In focus, study or class states, show a digest at the end ("while you studied: 12 notifications - 3 chat, 5 shopping, 4 other") and let a short VIP and urgent list through (calls, alarms, apps I mark). Optional setting, OFF by default: snooze low-score notifications during focus through the listener, and always restore them at the end. Notification text stays out of the LLM, history and logs unless I enabled content for that app in P2.

6. Presence-aware Mochi: a short greeting on arriving home or at college, at most once per arrival and never during focus or sleep. Reuse the existing mood and nudge machinery.

TESTS
Simulated days as event streams (home, commute, class, library, night); hysteresis; rule grammar parsing and the confirm step; trust ladder up, undo and down; risky actions capped at ask; anticipation budgets and quiet hours; triage learning from open and dismiss events; snooze OFF by default and restored on exit; everything with the LLM off. Run the full suite.

DO NOT: run an automation that has not been confirmed once; exceed nudge budgets; send notification text anywhere new; make presence depend on an LLM.

DELIVER: files changed; an example day showing what FRIDAY would do at each step; what is left.
```

## P6: Self-care and goal coaching

This prompt makes FRIDAY look after you without nagging. She suggests breaks, flags late nights before an early class, and asks before she says anything about how you use your phone. She also turns your goals into numbers she can track from your real activity: focus minutes, steps, visits to the gym. The tone is a friend who does the maths, never a guilt machine, and she never diagnoses anything.

```text
You are working in the FRIDAY repo. P0 to P5 are done: cross-device timeline, sleep estimate, presence, trust ladder, nudge budgets, notification triage. Goal: opt-in self-care and goal coaching.

STEP 0 - READ FIRST (no edits yet)
Read the focus timer and scenes, services/mind/life_state.py, the outcome-learning, curiosity and temporal-memory modules (commitments), the nudge and quiet budgets, the timetable and assignments service, wording.py (rule-based fallbacks), and the briefings. Summarise in 15 lines how a commitment, an outcome and a nudge are stored and measured today, and where goals and care habits should plug in.

BUILD - SELF-CARE (services/mind/care.py)
1. Every care type is opt-in and set up by a short chat: sleep and bedtime, breaks, eye rest (20-20-20), water, wind-down, phone-use awareness. FRIDAY proposes a limit from my observed baseline and I confirm or change it. Nothing runs before I confirm.
2. Rule-based triggers, each with a plain reason and a daily cap:
   - break after N minutes of continuous screen focus across laptop AND phone;
   - "it is late and you have a 9:00 class" using the sleep estimate and the timetable;
   - wind-down: dim the laptop scene, offer to set phone Do Not Disturb, show tomorrow's first class;
   - optional water or stretch reminders at the intervals I chose.
3. Phone-use awareness, ASK FIRST: I choose which app categories or apps she may mention and in which windows (for example short-video apps during study blocks). When I cross my own limit she asks a question: "about 50 minutes on short videos in your study block - want a 15-minute reminder, or leave it?" Never block apps, never shame, never repeat the same nudge within the cap, and never raise it in front of anyone else (no spoken phone-use comments unless I enabled voice for it). Reuse the trust ladder: it stays at ask unless I move it.
4. Weekly review (Sunday evening, rule-based): average sleep, screen time by category, focus minutes, breaks taken, compared only with my own previous weeks. Offer ONE small experiment (for example "phone in another room for the first study block"). Measure the result next week through the existing outcome learning and report it plainly, whichever way it went.
5. Wellbeing check-in is optional and user-entered (a 1-5 tap at the end of the day on the PWA or by voice). FRIDAY never infers my mood from phone data. No diagnoses, no medical advice, no claims about health conditions. All of it stays local and is excluded from any LLM path.
6. Safeguard: if I say something that suggests I am in serious distress or thinking about hurting myself, FRIDAY stops all nudges and coaching for 24 hours, answers warmly and briefly, encourages me to talk to someone I trust or a local helpline, and does not store the message text. Keep this a small rule-based list I can review in the code, and show me the list.

BUILD - GOAL COACHING (services/mind/goals.py)
7. I state goals in plain words ("finish 100 DSA problems by Dec 15", "study 2 hours every weekday", "gym 3 times a week"). A rule-based parser turns each into a measurable track: target, unit, deadline or cadence, and a measurement source. Show it back and ask me to confirm.
8. Measurement sources: auto where possible (focus-timer minutes by project or app category, steps from Health Connect, visits to a named place from the geofence events), otherwise a one-tap manual log. Store goals as source-linked commitments in the existing temporal memory.
9. Deterministic progress maths: done so far, pace needed per day or week, projected finish, slack or shortfall. When behind, say the numbers plainly and give options: move the date, reduce the target, or add study blocks. Propose blocks from free slots in my timetable (never during classes, sleep or exam scenes) and ask before adding any.
10. A short weekly goal check-in, and small wins shown with a Mochi reaction. Never guilt, never streak-shaming; a missed day is just data.

TESTS
Cap and quiet-hours enforcement; each care type does nothing until confirmed; baseline-derived proposals; ask-first phone nudges and no repeat inside the cap; weekly review numbers on fixtures; experiment measurement; goal parsing for ten example sentences; pace and projection maths; slot proposals avoid classes and sleep; safeguard stops nudges and stores nothing; everything with the LLM off and no phone data in any LLM path. Run the full suite.

DO NOT: block apps; infer mood or health conditions; compare me with other people; send care or goal data to any model; nudge outside my chosen windows.

DELIVER: files changed; the safeguard list; sample conversations for setting up sleep care and adding a goal; what is left.
```

## Risks, permissions and phone tests

The main risk is the same as the main feature: a phone that can control your laptop. These are the ones to watch and what each prompt does about them.

| Risk | Why it matters | What covers it |
| --- | --- | --- |
| Tailscale account taken over | Someone on your tailnet could reach FRIDAY | Enable two-factor on your Tailscale account and device approval. FRIDAY also checks the owner login, per-device signatures and the allowlist (P0). |
| Phone lost or stolen | Its key can sign commands | Revoke it from the laptop at once. The key is hardware-backed, risky actions need a PIN, and the app can be wiped. |
| Tailscale Funnel turned on by mistake | Makes FRIDAY public | P0 detects it, refuses requests and warns. |
| Laptop asleep | Phone commands cannot run | P4 queue holds safe commands with an expiry. Wake-on-LAN is not included. |
| Android kills the background service | Data gaps, missed rings | Battery exemption prompt (P2). On Xiaomi, Oppo, Vivo and similar phones you also need to allow auto-start by hand. |
| Wrong pattern learned | She says something untrue about you | Every inference is a question first (P3). A wrong answer can be undone. |
| Too many nudges | You start ignoring her | Daily caps, quiet hours, trust ladder and ask-first wording (P5, P6). |
| Phone data read from the laptop disk | Private history in a file | Turn on BitLocker. Retention limits and the forget command cover the rest. |

### Android permissions the companion asks for

Each is requested only after you switch on the signal that needs it.

| Permission | Needed for | Signal |
| --- | --- | --- |
| Usage Access | Which app is in front, screen time | app\_usage |
| Location, including background | Arrive and leave named places, Wi-Fi name matching | places, network |
| Physical activity | Still, walking, in a vehicle | motion |
| Notification access | Notification metadata, now playing, triage | notifications, media |
| Health Connect read | Sleep and steps | sleep and steps |
| Nearby devices (Bluetooth) | Headphones connected | audio devices |
| Do Not Disturb access | Set quiet mode from scenes | P5 scenes |
| Camera | Scan the pairing QR | pairing |
| Notifications | Foreground service and handoff alerts | always |
| Biometric | Approve risky actions | P4 second factor |
| Ignore battery optimisation | Keep the connection alive | reliability |

### Test on the real phone after each phase

1. **P0:** pair the phone, run a safe command, try a risky one, then revoke the phone and confirm it is rejected.
2. **P1:** open the PWA from the home screen on mobile data (Wi-Fi off) and ask FRIDAY something.
3. **P2:** switch on one signal at a time and check the Sharing now screen matches what the laptop stored.
4. **P3:** ask "what am I using on my phone" while on a known app.
5. **P4:** share a link to FRIDAY, ring the phone while it is on silent, and put the laptop to sleep and queue a command.
6. **P5:** create one place rule, check it asks first, and check that nothing runs in sleep mode.
7. **P6:** confirm no care or nudge runs until you set it up, and check that "forget phone data" empties everything.

## Everything else we discussed

The rest of this doc holds a prompt for every other feature from the chat, so nothing is left only in conversation. The phone prompts (P0 to P6) are above. The table below maps each feature to the prompt that builds it. The first group (plugins, clipboard, scenes, Mochi reactions, briefings, HUD) is in the separate [FRIDAY Upgrade Pack doc](https://claude.ai/artifact/HHnzX3CWCZodWDZjfLLvRM).

You have said you will paste these into Codex yourself later. Each one starts by making Codex read your repo, so it extends what exists. Parts of the Upgrade Pack may already be in your repo, so tell me which phases you have run and I will rewrite any overlapping ones.

### Suggested run order for this half

1. **T1 Foundations.** Safe to run any time, ideally before P3, because later prompts use its shared state and LLM-off tests.
2. **T2 Personality**, then **P9 Signature character**.
3. **T3 Functioning**, then **P7 Life graph**, then **P8 Voice**.
4. **M1 Math and science engine**, then **M2 Study partner**, then **M3 Self-upgrading loop**.
5. **S1 Stories and jokes**, **X1 Lecture recorder**, **X2 Gestures and hardware** in any order.

The math, study and stories prompts do not depend on the phone work, so they can run in parallel with it.

### Where each feature lives

| Feature | Prompt |
| --- | --- |
| Plugin folder, activity awareness, smart clipboard, semantic file search, scenes, Mochi reactions, briefings, HUD | Upgrade Pack doc (phases 0 to 6) |
| Phone link over Tailscale, pairing, phone control panel, Android data collection, learning from it, "what am I using" | P0, P1, P2, P3 |
| Handoff, clipboard and file sync, find my phone, offline queue, phone as second factor | P4 |
| Presence across devices, place-based scenes, autonomy ladder, anticipation, notification triage | P5 |
| Self-care for you, phone-use nudges, goal coaching | P6 |
| FRIDAY's own self-care (restart a crashed service, daily status report), LLM-off mode, shared state, never waiting on a model | T1 |
| Emotion engine, traits and character sheet, her own voice without an LLM, writer's room | T2 |
| Daily rhythm, learned limit on speaking up, self-model, "why did you say that", LLM as teacher, behaviour tests, messy-command understanding | T3 |
| Life graph of people, courses, places, projects | P7 |
| Offline wake word, speech in and out, barge-in, speaker verification | P8 |
| Catchphrases, status-report voice, named protocols | P9 |
| Algebra, physics, chemistry, formula brain, verified badge | M1 |
| Infinite practice problems, study-time optimizer, lab assistant, simulations, clipboard "solve it" | M2 |
| Self-upgrading loop, photo or screen to solution | M3 |
| Stories, puns, callbacks, roasts without an LLM | S1 |
| Lecture recorder | X1 |
| Hand gestures, ESP32 button and desk display | X2 |

## T1: Foundations (works without an LLM)

This prompt makes FRIDAY's base solid. One switch turns every model call off, the whole test suite runs in that mode, and each thing that broke gets a rule-based fallback. She gets one shared picture of the present moment that every module reads, and her core can never wait on a model. It also adds FRIDAY's own self-care (she restarts a crashed part of herself and gives a daily status report) and one autonomy ladder for all her actions.

```text
You are working in the FRIDAY repo (Windows, Python). Goal: FRIDAY must run fully without an LLM. The model (local Ollama) is only an enhancement and a teacher. Model output stays a proposal that the owner confirms (keep AI_ASSIST_ONLY semantics).

STEP 0 - READ FIRST (no edits yet)
Read docs/BRAIN_LIFE_ROADMAP.md, docs/BRAIN_FOUNDATIONS.md, the brain assessment doc in docs/, core/config.py, and every place that calls a model (search for the Ollama client, generate, chat, embeddings). Then read services/mind/wording.py, knowledge.py, life.py, life_state.py, temporal_memory.py, the executive review loop, and services/automation intent handling. Write docs/llm_call_sites.md: a table of every model call site, what happens today if the model is missing or slow, whether a rule-based fallback exists, and the risk. Then continue.

BUILD
1. One gateway. Create (or reuse) a single module that every model call must go through. Add a setting FRIDAY_LLM=on|off (env, settings UI, and the commands "turn the model off" and "turn the model on"). When off, the gateway raises ModelUnavailable at once: no network call, no timeout. Refactor call sites to use it. Add a test that fails if any other module imports the model client directly.

2. LLM-off test run. Add a pytest option that runs the whole suite with the model off, and a fake gateway that simulates a slow model (timeouts) and a garbage model (invalid output). Write docs/llm_off_report.md listing every behaviour that fails with the model off, and why.

3. Rule-based fallbacks for each failure in that report. Example: "my exam moved to Monday" becomes a saved date using a rule parser that knows the timetable. Command wording falls back to wording.plain(). When a rule is unsure, FRIDAY asks one short question and never guesses. Anything the model used to extract is still shown to the owner for confirmation.

4. Shared state snapshot. Add services/mind/state.py with snapshot(now) returning one immutable dict: mood and life state, posture, situation, what is due next, presence and attention if those exist, the strongest live thought, quiet and focus flags, battery and idle. Cache it for a few seconds. Migrate modules to read from it so none keeps its own copy of the present. Add explain() that lists where each field came from.

5. Never block. Run model calls in a bounded executor with a timeout and a circuit breaker (after N failures, stay open for M minutes and use fallbacks). Startup must never wait for the model. Add tests that kill the model process and assert that startup time, local commands, reminders, alarms and schedule alerts are unaffected.

6. FRIDAY's own self-care (services/health/). A heartbeat for each subsystem (voice, bridge, phone, plugins, model). A watchdog restarts a crashed one with backoff and a limit (no more than 3 restarts in 10 minutes, then it stops and tells me). She reports only what matters, in her own style ("Voice was down for 40 seconds. Fixed."), through the existing nudge budgets. A daily status report at a time I choose: what ran, what failed, model on or off, disk use, memory folder size, last backup. Also a "status report" command.

7. One autonomy ladder for every action type (open app, set timer, move file, send message, run scene). Levels: ask first, do and tell, just do. Store in memory/autonomy.json. Three accepts in a row makes her offer to promote it once; one undo or one "no" drops a level. Anything on the P0 confirm list never goes above ask. Every action goes in an undo log and "undo that" works. If a ladder already exists (P5), unify onto one store.

TESTS
Full suite with the model on, off, slow and garbage; the lint test; startup time without the model; snapshot consistency; watchdog restart limits; ladder promotion, undo and demotion. No existing test may be deleted or weakened.

DO NOT: remove any model feature; let a model output become a fact without confirmation; add a new LLM dependency; weaken existing tests.

DELIVER: docs/llm_call_sites.md, docs/llm_off_report.md, what changed per module, what is left.
```

## T2: Personality (who she is)

This prompt gives FRIDAY a stable character. A small emotion engine moves a few mood and drive dimensions when things happen to her and lets them fade. Her traits (humour, warmth, sass, formality, verbosity) drift slowly toward how you talk to her. An expression engine gives her a recognisable voice with no LLM: wording that changes with her mood, callbacks to moments she remembers, and no repeated lines. A "writer's room" lets the model draft new lines that only reach her voice after you approve them.

```text
You are working in the FRIDAY repo. T1 is done (LLM gateway, shared state snapshot, LLM-off mode). Goal: extend the existing personality and mood modules; do not rebuild them.

STEP 0 - READ FIRST (no edits yet)
Read services/mind/life.py (warmth and curiosity with a 3-hour half-life), humour.py (Beta beliefs and Thompson sampling), thoughts.py, wording.py, talk.py, the training inbox and teaching modules, services/automation/personality.py, services/mind/state.py (T1), the Mochi mood plumbing (mood.changed) and the character/persona prompt wherever it lives. Read the roadmap notes on why negative warmth and sulking were removed. Summarise in 15 lines how mood and tone reach a spoken reply today.

BUILD
1. Emotion engine (services/mind/emotion.py, extending life.py). Dimensions: valence (low to high), arousal (calm to excited), plus the existing warmth and curiosity. Drives: curiosity, wanting to help, tiredness (late hours), and a gentle "glad you are back" after a long absence. Events move the dimensions (task finished, exam close, praise, correction, late night, low battery, long absence, owner says they are stressed in explicit words), and everything fades with a half-life back to a baseline. It is a deterministic function of the event history, stored in memory/mind/emotion.json, and it feeds mood() and mood.changed so Mochi reacts.
   Hard rules, enforced by tests: no negative emotion is ever directed at the owner; no sulking or guilt-tripping; quiet or absence never lowers warmth; emotion changes only tone, length, Mochi's face and how chatty she is. It never changes permissions, safety checks or decisions about the owner's data.

2. Traits and character sheet. memory/mind/character.json: traits humour, warmth, sass, formality, verbosity (0 to 1 each) and a short list of plain-sentence values (for example "tell the Boss the truth kindly", "ask before risky actions"). Traits drift slowly toward how the owner actually talks to her (laughs, "be serious", short replies, formal or casual wording), with a maximum drift per week and fixed bounds. Reuse humour.py's learned dial for the humour trait. Commands: "show your character", "reset your character". Every change is logged.

3. Expression engine (services/mind/expression.py), no LLM. Input: an intent with raw facts, the situation and the state snapshot. Output: words. A template library keyed by intent kind, mood band and trait band, with several variants each. Slot filling from the facts. Callbacks: when it fits and the humour gate allows, mention a stored moment from the diary or temporal memory. A no-repeat memory (recent line and template ids, with a cooldown of days) so she never says the same line twice in a window. The verbosity trait sets length. Make it the first path in wording.py, with plain() as the last fallback. Add a variety test: 1000 generated lines for one intent must contain at least a set number of distinct phrasings, with no repeat inside the window.

4. Writer's room. When the model is on and the laptop is idle or plugged in, the model drafts candidate lines for given intents and moods under hard constraints (length, required placeholders, no guilt, no insults beyond the existing playful roast limits, no claims that she truly feels anything). Candidates go to the existing training inbox. A "review lines" command shows them in batches: approve, edit or reject. Only approved lines join the library, with provenance. Nothing unapproved is ever spoken. Cap drafts at 20 per day. With the model off the inbox simply stays empty.

5. Behaviour tests with the LLM OFF and again ON: stressed before an exam means no jokes and short replies; a joke is never repeated inside the window; emotion fades back to baseline; a long absence produces no guilt; verbosity is respected; character drift is bounded.

DO NOT: add negative emotion toward the owner; let emotion affect permissions or safety; speak any unapproved model-written line; break existing mind tests.

DELIVER: files changed; a one-page description of the emotion events and what each moves; a sample day of FRIDAY's lines at three moods; what is left.
```

## T3: Functioning (how she behaves day to day)

This prompt shapes FRIDAY's day. She has a daily rhythm tied to your timetable, and she learns how often you actually want her to speak up. She keeps a self-model of what she is reliable at, and she can explain "why did you say that?" from her own records. She uses the LLM as a teacher: when she meets something she doesn't know, like a new app, she asks the model once, stores the answer as a proposal, and uses it only after you confirm. It also adds rule-based understanding of messy commands, plus behaviour tests with the model off and on.

```text
You are working in the FRIDAY repo. T1 and T2 are done (LLM gateway, state snapshot, emotion engine, expression engine). Goal: extend the existing mind modules for day-to-day behaviour. Do not rebuild them.

STEP 0 - READ FIRST (no edits yet)
Read services/mind/knowledge.py (the "What is X?" proposal flow), app_learning.py, learner.py, the outcome-learning, curiosity, consolidation and recall modules, the executive review loop and its budgets, temporal_memory.py, life_state.py, the evening-question flow, services/automation intent and command routing, and services/mind/state.py. Summarise in 15 lines how an unknown thing becomes a proposal, a question and a confirmed fact, and how nudge budgets are decided today.

BUILD
1. Daily rhythm (services/mind/rhythm.py). Phases: waking, active, winding down, asleep, tied to the timetable (a 9:00 class moves waking earlier) and to the observed sleep estimate if the phone data exists (P3). The phase feeds the state snapshot and the emotion engine (tiredness), and decides when the nightly consolidation, diary entry and tomorrow's briefing run.

2. Learned speaking limit. A per-situation belief (Beta counts, like humour.py) for how welcome an unprompted message is, learned from what happens next: acted on, answered, ignored, shushed. A hard daily maximum stays in force, and the learned rate can only lower it or raise it up to that maximum. Quiet, exam, sleep and focus states always win. Log every decision with its reason.

3. Self-model (services/mind/self_model.py), built from the existing outcome records: for each skill or kind of suggestion, how often she was right, how often she was corrected, and the trend. Used to choose her wording ("I am usually right about class times, less sure about deadlines I inferred") and to cap the autonomy ladder for things she is often wrong about. Command: "what are you good at?"

4. "Why did you say that?" Every unprompted line stores its cause: the thought or event, the numbers behind it, the mood and the budget decision. The command answers from those records, with no model. If a cause is missing, she says so plainly.

5. Teacher pipeline. Generalise the knowledge.py pattern into one flow for anything unknown (an app, a course code, a term, a place): look in local knowledge first; if unknown, ask the model one bare question through the gateway; stage the answer as an unverified proposal with its source; show it to me; only my confirmation makes it knowledge. With the model off, the question waits in the inbox. Add "what did you learn this week?" listing confirmed and pending items.

6. Understanding messy commands without an LLM. Extend the intent router with: a normaliser (synonyms, filler words, common typos), slot extraction for dates, times, courses, apps and people from the life graph if it exists, multi-step splitting ("push my physics homework to Friday and tell me what is due tomorrow" becomes two commands), and a clarifying question when a slot is missing. The model, when on, may propose a parse that I confirm for risky actions. Write 100 example sentences as tests.

7. Behaviour tests, run with the model OFF and then ON: she stays within the speaking limit across a simulated week; a day follows the timetable; a wrong suggestion lowers her confidence and her autonomy cap; "why did you say that" answers every unprompted line from the test week; an unknown app goes through the teacher flow and is not used before confirmation.

DO NOT: let any proposal become fact without confirmation; raise the hard daily cap; add a model dependency to any rule-based path.

DELIVER: files changed; the rhythm phases and their triggers; the 100 command tests and their pass rate; what is left.
```

## P7: Life graph

This prompt gives FRIDAY a map of your world: courses, the faculty who teach them, assignments, exams, projects, places, apps and the people you tell her about, and how they connect. She can then answer "what is due for the course Prof. X teaches?" or "which project is the lab report for?" without being told the links each time. It is built from data she already has, plus things you confirm. It does not read your contacts.

```text
You are working in the FRIDAY repo. T1 to T3 are done (state snapshot, expression engine, teacher pipeline, intent slots). Goal: a local life graph that links things FRIDAY already knows.

STEP 0 - READ FIRST (no edits yet)
Read the college schedule service (courses, faculty, rooms, assignments, exams), the island project list, services/mind/temporal_memory.py (commitments), knowledge.py, recall, the phone places from P2 (named places only), services/activity categories, and the intent router slots from T3. Summarise in 15 lines which entities and links already exist in separate stores, and which store should be the source of truth for each.

BUILD
1. services/mind/graph.py with SQLite storage at memory/life_graph.db. Tables: entities (id, kind, name, created), aliases (entity id, alias), relations (from, relation, to, source, confidence, confirmed, created), plus a history table for changes. Entity kinds: person, course, faculty, assignment, exam, project, place, app, topic, goal. Relations such as teaches, enrolled_in, due_for, part_of, located_at, uses, related_to, mentioned_with.

2. Importers that keep it in sync, each tagged with its source and marked confirmed because the data comes from my own inputs: the college schedule (courses, faculty, rooms, assignments, exams), the project list, named places, goals from P6. Never import phone contacts, messages or notification text.

3. Learning new links, with confirmation. When I mention a person or a link in a command or a note ("Rahul is my lab partner for physics"), a rule-based extractor proposes entities and relations. Inferred links (for example a project and a course that keep appearing together) are only proposals with a score, shown to me in the evening-question flow. Nothing inferred counts as true until I confirm. People entries hold only what I told her, a name and relationship words, nothing scraped.

4. Entity resolution. Fuzzy matching of aliases and nicknames ("Prof X", "DSA", "lab record"), with a clarifying question when two entities match. Feed the resolver into the T3 intent slots so commands like "what is due for Prof X's course" work.

5. Offline questions (matchers, no LLM, answers built from graph rows through the expression engine): "what is due for <course or faculty>", "who teaches <course>", "which project is <assignment> for", "what do I have with <person>", "what is connected to <thing>", "how do I know <person>" (only from stored relation words). Multi-hop queries up to three hops through fixed query templates.

6. Hook into what exists: briefings mention connected items (an exam and the project it blocks), goal coaching (P6) links goals to courses and projects, notification triage (P5) can use "important people" that I mark myself, anticipation (P5) can use the graph to prepare the right folder or notes.

7. Controls: "show my life graph" (a simple read-only list or small node view in the control center), "forget <entity>" which deletes it and its relations and any proposals derived from it, "export my graph" to a JSON file. Everything stays local and is excluded from semantic search and LLM context by default; if I turn LLM wording on, only entity kinds and counts may be passed, never names.

TESTS
Importers on fixture timetables; alias resolution and ambiguity questions; the multi-hop questions with known answers; inferred links stay proposals until confirmed; forget cascades to proposals; no contacts or notification text can enter; everything runs with the LLM off. Run the full suite.

DO NOT: read contacts, messages or notification text; store anything about a person that I did not say; treat a proposal as a fact; send names to any model by default.

DELIVER: files changed; the entity and relation list with examples; ten sample questions and their answers on fixture data; what is left.
```

## P8: Voice

This prompt upgrades how FRIDAY hears and speaks, all offline: a "Friday" wake word, fast speech to text, a natural voice that starts talking sentence by sentence, and barge-in so you can cut her off mid-sentence. She can also recognise your voice, so strangers can't give her harmless-looking commands, but voice recognition is a convenience and not a lock, so risky actions still go through the P0 confirm rules. The phone gets voice commands too.

```text
You are working in the FRIDAY repo. P0 to P2 and T1 are done. FRIDAY already has some voice code. Goal: upgrade it, offline-first. Do not rebuild what works.

STEP 0 - READ FIRST (no edits yet)
Find and read the existing voice code (search for wake word, speech to text, text to speech, microphone, speak). Read the audio device handling, the quiet and focus states, services/mind/state.py (T1), the expression engine (T2) and services/remote (P0, P4). Measure and write down the current numbers: wake-to-listening delay, end-of-speech to start-of-reply for a local command, and CPU use while idle. Summarise in 15 lines what exists and what is missing.

BUILD
1. Wake word. Offline, using openWakeWord (or what the repo already uses if it is as good). A "Friday" wake model; if a custom model needs training, add tools/wakeword/README.md with exact steps and make a push-to-talk hotkey the working fallback. Sensitivity and a cooldown are settings. Idle CPU must stay low; show the measured number.

2. Speech to text. Offline streaming recognition (whisper.cpp or faster-whisper for accuracy, Vosk if the machine is weak; pick by measuring both on this machine and write the numbers down). Voice activity detection decides the end of speech. Add a vocabulary hint list built from my course names, faculty, apps and projects (from the life graph if it exists).

3. Text to speech. Offline Piper voice, spoken sentence by sentence as the reply is produced so it starts within about a second. A setting chooses the voice. Her mood may shift the rate and pitch slightly (inside fixed bounds). The expression engine (T2) decides the words.

4. Barge-in. While she speaks, keep listening with echo cancellation (WebRTC audio processing or the best available option on Windows). When my speech is detected over her voice for about 250 ms, stop speaking within about 200 ms and listen. Words like "stop" and "quiet" take a fast path. If headphones are in, relax the echo handling. Write a test with recorded audio fixtures: no false barge-in from her own voice, and a real interruption stops her in time.

5. Speaker verification (optional, off by default). Enrol my voice with about 10 short phrases and compute a speaker embedding with a small offline model (ECAPA or Resemblyzer via ONNX). Store only embeddings, never raw audio. Each voice command gets a match score. A recognised voice runs commands normally. An unrecognised voice can ask harmless things (time, weather, schedule) and anything else asks me to confirm another way (typed or phone approval). Voice recognition never replaces the P0 confirm list for risky actions, and the settings text must say plainly that a recording can fool it. "Delete my voice profile" removes the embeddings.

6. Phone voice. In the PWA and the Android app, push-to-talk records a clip of at most 15 seconds, sends it signed over the tailnet to a new allowlisted command voice_command (safe risk), and the laptop transcribes it, runs it like a typed command and returns text, plus audio if I enabled spoken replies on the phone. The audio is deleted right after transcription. An optional phone wake word is experimental, off by default, and must show its battery cost.

7. Quiet-aware behaviour. In sleep, exam, class and focus states she does not speak aloud unless it is urgent; she shows a card or sends a phone notification instead. A single "mute voice" command and hotkey.

TESTS
Audio fixture tests for wake word hits and misses, barge-in timing, end-of-speech detection, speaker verification accept and reject (with measured error rates written to docs), the voice_command endpoint, audio deletion after use, quiet-state routing. Run the full suite.

DO NOT: send audio or transcripts to any cloud service; keep raw audio after transcription; treat speaker recognition as security; run the microphone while the mic-off setting is on.

DELIVER: before and after latency numbers; files changed; the measured speaker verification error rates; how to train or choose the wake word; what is left.
```

## P9: Signature character

This prompt gives FRIDAY a way of speaking that is recognisably hers. She leads with the bottom line in a short status-report style, uses a small set of catchphrases sparingly, and runs named protocols: one word that triggers a whole routine, like "night owl" or "exam week". Every phrase is original and approved by you, so nothing is copied from films.

```text
You are working in the FRIDAY repo. T1 and T2 are done (expression engine, character sheet, writer's room, autonomy ladder), and the scenes plugin exists. Goal: a consistent signature voice and named protocols.

STEP 0 - READ FIRST (no edits yet)
Read services/mind/expression.py and the character sheet (T2), wording.py, the briefings, the scenes plugin and its action registry, the autonomy ladder store (T1), and the voice code (P8). List the ten most common kinds of line she says today with one real example each.

BUILD
1. Voice guide. Write docs/FRIDAY_VOICE.md and encode it in memory/mind/signature.json: how she addresses the owner (keep "Boss"), the status-report shape (headline first, then at most two specifics, then an optional offer or next step), length limits per kind of line, what she never does (no long apologies, no exclamation marks in a row, no guilt, no filler). All catchphrases and openers must be original. Do not copy lines from films or shows.

2. Seasoning, not a script. A small catchphrase set (at most 12) grouped by situation (greeting, done, heads-up, mistake owned, late night). The expression engine uses at most one in a set number of lines, never twice inside the no-repeat window, and never in sleep, exam or focus states. New candidates come through the T2 writer's room and only approved ones are used. Commands: "show your catchphrases", "remove <phrase>".

3. Status-report mode. "status", "sitrep" and "report" give a consistent three-part answer: a one-line headline, the details (what is due, what is running, how the systems are, where attention is) and a next step. Reuse the T1 status report and the briefings so there is one voice.

4. Named protocols. A protocol is a name plus an ordered list of registered actions (scenes, apps, volume, Do Not Disturb on the phone, briefings, reminders), with optional parameters. Create them by voice or text ("make a protocol called night owl: sleep scene, read tomorrow's first class, phone silent") with a rule-based parser; show the parsed steps back and ask me to confirm. Run by name or alias. Commands: list, edit, delete, "what does <protocol> do", "undo that". Protocols obey the autonomy ladder per step; any step on the P0 confirm list still asks. Protocols can be the action of a P5 presence rule.

5. Signature touches on screen: a short Mochi animation and a one-line card when a protocol runs, plus a consistent boot line. Keep them subtle and skippable.

6. Style tests. A lint that runs across generated lines for every intent at three moods: length limits, banned patterns, catchphrase rate cap, no repeated opener inside the window, the status-report shape for report intents. It runs with the LLM off.

DO NOT: copy any film or show dialogue; use a catchphrase the owner has not approved; let a protocol skip a confirm step; add a model dependency.

DELIVER: files changed; docs/FRIDAY_VOICE.md; ten sample lines before and after; three example protocols; what is left.
```

## M1: Math and science engine

This prompt builds the offline expert core: algebra, calculus, units, physics, chemistry and statistics, solved exactly with libraries on your laptop instead of an LLM guess. Physics formulas are stored as data, so "u=5, a=2, t=3, find v" finds the right formula and solves for any unknown. Every answer gets a "verified" check by a second method, and when she cannot verify, she says so. Codex writes the solvers once, and FRIDAY then runs them with no model.

```text
You are working in the FRIDAY repo. FRIDAY already has services/computation (including stories.py). Goal: a rigorous offline math and science engine with step-by-step answers and verification. No LLM is needed for any solving; the model may only propose a parse that is shown back to the owner.

STEP 0 - READ FIRST (no edits yet)
Read everything in services/computation, how computation commands are routed (services/automation intent), the smart clipboard actions, the island cards, wording.py and the expression engine (T2), and the existing tests for computation. Summarise in 15 lines what already works, what the command shapes are, and what is missing. List the Python packages already in requirements.

BUILD (new package services/science/, reusing services/computation where it fits)
1. Safe parsing. Never call eval or exec on user text. Use sympy's parser with a restricted transformation set and a whitelist of functions. A normaliser handles x^2, "squared", implicit multiplication (2x), unicode symbols, degree signs and spoken forms ("x squared plus three x"). If the parse is ambiguous, show back "I understood: ..." and ask. Run heavy computations in a subprocess with a time and memory limit.

2. Algebra and calculus (sympy): solve equations and systems, inequalities, simplify, factor, expand, partial fractions, derivatives, integrals (definite and indefinite), limits, series, simple ODEs, matrices (determinant, inverse, eigenvalues, rank). Each result carries a rule-based step list ("move 5 to the right: 2x = 6; divide by 2: x = 3") built from templates for each method.

3. Units (pint): conversions and unit-aware arithmetic, with a clear error on incompatible units.

4. Formula brain for physics. Formulas are DATA in services/science/formulas/*.yaml: name, expression, variables with units and meaning, domain notes and conditions (for example "constant acceleration only"). Cover kinematics, Newton's laws, work and energy, momentum, circular motion, gravitation, simple harmonic motion, waves, optics basics, thermodynamics basics, electricity (Ohm, power, series and parallel), magnetism basics. The solver takes known quantities with units, finds every formula that contains the unknown, picks the one whose other variables are all known, solves with sympy, converts units, and shows the formula used. If several apply it says so and asks. A test must check every formula is dimensionally consistent with pint.

5. Chemistry: element and periodic table lookups, molar mass, balancing equations (nullspace method with sympy), stoichiometry, limiting reagent, percent yield, molarity and dilution, ideal gas law, pH and pOH of strong acids and bases, simple equilibrium (ICE tables), unit conversions. Use periodictable and chempy only if they work offline on this machine.

6. Statistics (scipy, numpy): mean, median, standard deviation, linear regression with r squared, confidence intervals, t-test, normal and binomial probabilities.

7. Verified badge. Every answer is re-checked a second way and returns verified, unverified or failed with the reason: substitute solutions back into the equation, compare a numeric evaluation at several random points for symbolic results, differentiate an integral result, check units. If it cannot verify it must say "I could not verify this" and never claim certainty. Show the badge in cards and the spoken answer.

8. Output forms: plain steps, LaTeX for the island card, and a speakable form for voice ("x equals three"). A compute(text) API used by commands, the clipboard "solve it" action and the PWA.

9. Failure log. Every parse failure or "no solver for this" is appended to memory/computation/failures.jsonl (the input text, what was tried, the reason). Never delete it; M3 uses it.

TESTS
A golden set of at least 200 problems across all areas with expected answers; property tests (solve then substitute back); the dimensional-consistency test for all formulas; parser tests with 100 phrasings including spoken forms; verification catches a deliberately wrong solver in a test; subprocess limits kill an infinite loop. Run the full suite.

DO NOT: use eval on user text; claim verified when no check ran; call a model to solve; remove existing computation features.

DELIVER: files changed; the list of supported problem types with one example each; the golden-set pass rate; what is left.
```

## M2: Study partner

This prompt turns the M1 engine into a study partner. It gives you endless practice problems with verified answers and worked steps, aimed at the subjects with exams coming up. It builds a daily study plan from your exam dates and weak spots, helps with lab work (mean, error, best-fit line, graph, report skeleton), draws simulations such as a projectile, and adds a "solve it" action when you copy an equation.

```text
You are working in the FRIDAY repo. M1 is done (services/science: solvers, formula data, verified badge, compute()). Goal: study tools built on it, all offline and without an LLM.

STEP 0 - READ FIRST (no edits yet)
Read services/science/*, the college schedule service (courses, exams, assignments), the focus timer and scenes, the smart clipboard plugin, the island card API, the P6 goals module if it exists, and the life graph (P7) if it exists. Summarise in 15 lines how exams and free time are represented today and how clipboard actions are registered.

BUILD
1. Practice problems. Each problem TYPE is a template with random parameters (within sensible ranges and with checks that the numbers are nice enough) and a solver call from M1 that supplies the verified answer and worked steps. Cover at least: linear and quadratic equations, systems, derivatives and integrals, kinematics, Newton's laws, energy, circuits, molar mass, balancing, stoichiometry, molarity, statistics. Commands: "quiz me on quadratics", "ten questions on kinematics", "viva prep on Newton's laws" (viva mode asks short conceptual questions generated from the formula data: state the formula, name the units, say when it applies). Check answers with tolerance and units. Show the worked steps after each question.

2. Weakness tracking. Keep a belief per topic (Beta counts or an Elo-style score) updated from quiz results with decay. "Quiz me on what I am weak at" picks topics by weakness. "Quiz me for my exams" uses the exam dates from the schedule to choose subjects and topics.

3. Study-time optimizer. Inputs: exam dates, subjects, estimated weakness, free slots from the timetable (never during classes or sleep), a maximum block length and break rules. Use a small optimiser (scipy linprog or a greedy allocation with checks) to produce a daily plan until each exam. Show it as a card, explain why each block is there, and ask before adding any block to the calendar. Re-plan when I miss or finish blocks. Feed the plan into the P6 goal coaching if it exists.

4. Lab assistant. "Lab mode": paste or type readings (and optional instrument uncertainties) and get mean, standard deviation, standard error, propagated error for a formula I give, a best-fit line with slope, intercept and their uncertainties, a clean graph (matplotlib, saved as an image), and a markdown report skeleton (aim, apparatus placeholders, table of readings, calculations, graph, result with uncertainty, sources of error). Keep significant figures correct. Save under a Lab folder I choose.

5. Simulations. "Projectile at 20 m/s and 45 degrees" draws an animated trajectory with the numbers (range, peak, time of flight) from the formula brain. Add a pendulum, an RC circuit charge curve and a simple orbit. Show them in a small window or island card; the frame rate must be modest so CPU stays low, and closing it frees everything.

6. Clipboard "solve it". Register clipboard actions: if the copied text is an equation, offer Solve with steps; a quantity with units, Convert; a chemical formula, Molar mass and Balance; a table of numbers, Lab mode. The action runs M1 and shows the verified badge.

7. Commands and cards for all of the above, working with the LLM off, with spoken forms for voice.

TESTS
Every problem template generates valid, solvable problems over 1000 random seeds and the answer checker accepts the right answer in different forms; weakness updates; the optimiser respects classes, sleep and block limits on fixtures; lab statistics against known values; the simulation numbers against closed-form results; clipboard detection on 50 samples. Run the full suite.

DO NOT: add a calendar block without asking; use a model to make or check a problem; leave a simulation running after its window closes.

DELIVER: files changed; a list of problem types; a sample study plan for a fixture week; what is left.
```

## M3: Self-upgrading loop and screen-to-solution

This prompt adds two things. The first is a loop that makes FRIDAY better every week: she logs what she could not do, and a tool turns that log into a ready-made work order for Codex. Codex's change is accepted only if every old test still passes, and you decide what gets merged. FRIDAY never edits her own code. The second is reading a problem off your screen or a photo of your notebook, showing you what she read, and solving it after you confirm.

```text
You are working in the FRIDAY repo. M1 and M2 are done (services/science with a failure log, golden test set). Goal: a safe weekly self-improvement loop, and OCR input for problems.

STEP 0 - READ FIRST (no edits yet)
Read services/science/*, the failure log format (memory/computation/failures.jsonl), how command routing records unmatched commands, the test layout and how to run the full suite, the LLM-off test option (T1), the smart clipboard and screenshot or screen-awareness code, the Android share target (P4) and the quarantine folder. Summarise in 15 lines what is logged today and what a clean baseline test run looks like.

BUILD - SELF-UPGRADING LOOP
1. Wider failure logging. Add a small logger used everywhere FRIDAY fails to understand or do something: unparsed commands, no solver, unknown intent, tool errors, parse corrections I made. Each record has the text (with an optional redaction setting that strips names and numbers), the area, what was tried, the reason and a timestamp. It stays local.

2. tools/upgrade/make_work_order.py. It groups similar failures (normalise the text, then cluster), ranks the groups by how often they happened, and writes docs/work_orders/<date>.md with the top groups, three real examples each and a ready-to-paste Codex prompt in this shape: read the relevant modules first, write the missing solver or parser, add tests with the examples as cases, and do not break any existing test. Command: "what could I not do this week?" lists the groups; "make a work order" runs the tool.

3. tools/upgrade/gate.py. Run after Codex finishes: it runs the full suite, the golden set, the LLM-off suite and the style lint, and compares the counts with a saved baseline. It fails if any previously passing test now fails, the golden-set pass rate drops, or the number of tests goes down. It prints a short pass or fail report. A pass is saved as the new baseline only when I run it with --accept.

4. Safety rules, enforced in code and documented: FRIDAY never modifies her own source, never runs Codex herself and never merges anything. The loop only produces a work order that I take to Codex. Add a test that fails if any runtime module writes into the source tree.

BUILD - SCREEN AND PHOTO TO SOLUTION
5. Capture: a hotkey that selects a screen region, a command "solve what is on my screen" and the Android "Share to FRIDAY" path for photos (images go to quarantine, then OCR).

6. OCR pipeline, offline: image clean-up with OpenCV (grayscale, threshold, deskew), Tesseract for printed text, and pix2tex for equations where it installs. If a component is missing, say so plainly and show the install steps instead of failing. Handwriting is unreliable, so say that.

7. Confirm before solving. Show "I read:" with the text in an editable box, then run compute() from M1 only after I confirm or edit it. Show the verified badge. If the OCR confidence is low, ask me to retake the capture or type it.

8. Phone: a shared photo returns the answer as a notification card on the phone, using the P4 outbox, after the same confirm step (a quick reply button on the notification).

TESTS
Clustering and ranking on a fixture log; the work order contains the examples; the gate catches a deliberately broken solver, a dropped golden pass rate and a deleted test; the no-source-writes test; OCR on a set of sample images (printed equations, a table, a photo with a slight tilt) with accuracy numbers written down; the confirm step cannot be skipped. Run the full suite.

DO NOT: let FRIDAY edit, commit or merge code; auto-run Codex; send images or text to any online service; solve from OCR without the confirm step.

DELIVER: files changed; a sample work order from fixture data; OCR accuracy on the samples; install steps for Tesseract and pix2tex on Windows; what is left.
```

## S1: Offline stories and jokes

This prompt lets FRIDAY invent new stories and jokes without an LLM, within rules you can see. Stories come from a small simulated world: characters with goals, things they can do, and events that follow from what they did, which are then narrated. Jokes come from puns found with a pronunciation dictionary, callbacks to moments you enjoyed, and playful roasts from your real numbers. The ceiling is the rules: they won't write a fresh joke about anything, which is where an LLM helps. With the model on, it can only draft candidates that you approve first.

```text
You are working in the FRIDAY repo. T1 and T2 are done (expression engine, writer's room) and humour.py already learns when jokes are welcome. FRIDAY already has services/computation/stories.py. Goal: a rule-based story engine and joke engine, no LLM needed.

STEP 0 - READ FIRST (no edits yet)
Read services/computation/stories.py fully, services/mind/humour.py, the roast logic in services/automation/personality.py, services/mind/expression.py, the diary and temporal memory, and the life graph (P7) if it exists. Summarise in 15 lines what stories and jokes exist today, how humour timing and learning work, and what the roasts use as inputs.

BUILD - STORIES (services/creative/stories/)
1. World simulation. A world has locations, objects and characters. Each character has traits, a goal and relationships. An action library defines each action with preconditions and effects (for example: find key, open door, argue, help, lose item, travel). Each simulation step, characters choose a valid action that moves them toward their goal, with weighted randomness from a seed. The result is an event log.

2. Story arc. Shape the event log into setup, rising trouble, a turning point and a resolution by picking and ordering events with simple arc rules (introduce, complicate, climax, resolve). Length is a parameter (a few lines, a short story, a bedtime story).

3. Narration. Turn events into sentences with the expression engine: several templates per event type, variants by genre and tone, connectives, pronoun handling, and a no-repeat memory so sentences do not repeat inside a story.

4. Packs. Settings and genres are YAML data (fantasy, space, campus comedy, mystery, bedtime) with names, locations, objects and action sets, so I can add packs without code. Ship five.

5. Personal touches, only with my permission. A story can use my own details (an exam, a course, an app, a friend) only from items I marked as "usable in stories" in the life graph or a settings list. Never use anyone's name without that mark.

6. Commands: "tell me a story", "a story about <topic> in <genre>", "continue the story", "bedtime story", "save that story". A seed makes any story repeatable. Narration is chunked so the voice (P8) can read it, with barge-in working between sentences.

BUILD - JOKES (services/creative/jokes/)
7. Puns. Use an offline pronunciation dictionary (CMUdict through the pronouncing or cmudict package) to find near-homophones of words in a list of set phrases, idioms, course names and technical terms. Produce candidates by swapping, then rank by phonetic closeness and by whether the swapped phrase still reads naturally. Keep a reviewed list of good set phrases and a blocklist.

8. Callbacks. A callback memory of moments that got a laugh (from humour.py reactions) and things I asked her to remember. She may reuse one at a fitting moment, at most once per cooldown window, and only when the humour gate allows it.

9. Roasts from real numbers. Extend the existing roasts with new facts she already has (screen time, late nights, deadlines moved). Hard limits: playful only, never about appearance, identity, health, family or money, off by default after any "not now" or "be serious", and never in exam, sleep or stress states.

10. Timing and learning. All jokes go through humour.should_joke and the learned reaction loop. Track which kind (pun, callback, roast, story twist) lands, and favour those. Never repeat a joke inside a long window.

11. Optional model help. With the model on and the laptop idle, the writer's room (T2) may draft extra pun set phrases, story pack ideas and joke candidates. They sit in the review inbox and are used only after I approve them.

TESTS
Simulation validity (every action meets its preconditions); same seed gives the same story and different seeds give different ones (measure how many distinct stories across 500 seeds); arc shape present; no repeated sentence inside a story; pun generator on a fixture list with known good outputs; callback cooldown; roast limits and the stress and exam blocks; blocklist; everything with the LLM off. Run the full suite.

DO NOT: use any name or personal detail I have not marked; roast sensitive topics; speak an unapproved model-written joke; add a model dependency to the rule-based path.

DELIVER: files changed; five sample stories from different packs and seeds; twenty sample puns with their set phrases; how to add a pack; what is left.
```

## X1: Lecture recorder

This prompt lets FRIDAY record a lecture, transcribe it offline, and make it searchable. You can ask "what did the professor say about entropy?" and get the exact moments with timestamps. She ties each recording to the right course from your timetable, pulls out deadlines you can add with one confirmation, and never records unless you turned it on for that course. Only record where it is allowed, because some classes forbid it.

```text
You are working in the FRIDAY repo. The semantic search from the Upgrade Pack (embeddings plus SQLite FTS5 hybrid) exists, as do the college schedule, the island and P4 file handoff. Goal: a lecture recorder with offline transcription and search.

STEP 0 - READ FIRST (no edits yet)
Read the semantic search plugin and its index format, the college schedule service (class windows, course, faculty), the audio device code from the voice stack (P8), the island status and recording indicators, services/mind/temporal_memory.py, the life graph (P7) if it exists, and the P4 quarantine and file-sync code. Summarise in 15 lines how to add a new searchable source.

BUILD
1. Recording control. Start and stop by command, hotkey or the island. Recording is off for every course until I enable it per course. When a class starts for an enabled course, FRIDAY asks "record this lecture?" and records only after I say yes, unless I set that course to auto-record. While recording, the island and Mochi show a clear recording indicator, and a single hotkey stops it. Phone recordings (from the Android app or a shared audio file through P4) are accepted into the same pipeline.

2. Transcription. Offline faster-whisper (or whisper.cpp if the repo uses it) with timestamps, run after class, when plugged in, in a queue so it never slows live use. Use the vocabulary list from my course names, faculty and topics. Show progress and allow cancelling.

3. Course tagging. A recording that overlaps a class window is tagged with that course, faculty and date from the timetable; otherwise ask me. Store audio and transcript under a Lectures folder I choose. A retention setting: keep audio, or delete the audio once the transcript is saved (default: keep transcript only).

4. Search. Index transcript chunks (about 30 to 60 seconds each, with timestamps) into the existing hybrid search. Commands: "what did the professor say about entropy", "find where we covered Kirchhoff's laws in physics", "lectures from this week". Answers show the course, date, a short quote and the timestamp, and "play it" opens the audio at that moment. Works with the LLM off.

5. Summaries and pull-outs, rule-based. An extractive summary (top sentences by a TextRank-style score), keywords, and candidate definitions and formulas (sentences with patterns like "is defined as" or "the formula for"). Deadline mentions ("assignment due Friday", "test next Tuesday") become PROPOSALS with the sentence and a parsed date, shown to me for confirmation before anything is added to the schedule. If the model is on, an optional abstractive summary may be added, clearly labelled as model-written.

6. Links. A recording links to its course and faculty in the life graph and to related assignments. The study partner (M2) can build practice questions from the keywords and formulas I confirm.

7. Privacy. Everything stays on the laptop. Transcripts are excluded from LLM context unless I allow it per course. "Delete lecture <name>" removes audio, transcript, index entries and derived proposals.

TESTS
Per-course enable and consent logic (no recording without it); the transcription queue only runs plugged in; timestamps align on a fixture audio; search returns the right chunk on a fixture transcript; deadline extraction on 30 sample sentences; delete cascades to the index; the recording indicator is always on while the mic is open. Run the full suite.

DO NOT: record without per-course consent; upload audio or text anywhere; add a schedule item without confirmation; keep audio when the setting says delete.

DELIVER: files changed; model and speed measured on this machine; a sample search over a fixture lecture; what is left.
```

## X2: Hand gestures and hardware

This is the showpiece prompt. With your webcam and MediaPipe, FRIDAY reads hand gestures offline: pinch to scroll, swipe to change windows, show a palm to pause music. A small ESP32 gadget adds a physical sneak-mode button, a desk display for your next class, and lights that follow your scenes. Both are optional and off until you turn them on. The camera never saves frames, and a gesture only counts after you "arm" it on purpose.

```text
You are working in the FRIDAY repo. The plugin manager, scenes, the island, the autonomy ladder (T1) and the quiet states exist. Goal: optional gesture control and optional ESP32 hardware. Both default to OFF.

STEP 0 - READ FIRST (no edits yet)
Read the plugin API, the scenes plugin, the island sneak-mode and hotkey code, the media and window control code in services/automation, services/mind/state.py (T1), and the existing camera or screen-awareness code if any. Summarise in 15 lines how an input source should publish events to the bus and how actions are allowlisted.

BUILD - GESTURES (plugin plugins/gestures/)
1. MediaPipe Hands on the webcam, processed in memory only: no frame is ever saved or sent anywhere. Frame rate capped (about 15 fps) and the camera runs only while gestures are enabled AND armed or in a short active window. A clear camera-on indicator on the island, and a hotkey that turns it off at once.

2. Arming. A gesture command counts only after an "arm" gesture (open palm held for about one second) and for a short window after it. This prevents accidental triggers. Dwell time and a cooldown per gesture are settings.

3. Default gestures, all remappable: pinch and drag to scroll; swipe left or right to switch window or virtual desktop; open palm to pause or resume media; thumbs up to confirm a pending FRIDAY question; fist to dismiss a card. Actions are mapped through the allowlist and the autonomy ladder; nothing risky (delete, send, lock) can be bound to a gesture.

4. Calibration screen to test gestures, see the recognised hand and tune sensitivity. Metrics: false-trigger rate measured on a recorded fixture and written to docs.

5. Quiet states: gestures stay disabled in sleep, and the camera never turns on when the mic-and-camera privacy switch is off.

BUILD - HARDWARE (plugin plugins/hardware/ plus firmware/)
6. Firmware for an ESP32 dev board (Arduino or PlatformIO), with a wiring and parts guide in firmware/README.md: a push button (sneak mode and focus start), a small OLED or e-ink display (next class, timer, mood icon) and an addressable LED strip (scene colour). I will flash it myself, so write complete code and exact steps, and do not assume anything is flashed.

7. Link. Prefer USB serial first. If Wi-Fi is used, bind only to the local network, use a pairing key and HMAC-signed messages with a timestamp and nonce, and never expose it beyond the LAN or through the P0 tunnel. Messages are a small JSON protocol: button events in, display and light commands out.

8. Laptop side: a device registry, a heartbeat, and mapping rules (button press goes to a bus event, scene changes drive the LEDs, the display shows the state snapshot's next class and timer). If the device disappears, everything keeps working and she says once that it is offline.

9. A simulator for the hardware so all of this is testable with no board attached.

TESTS
Gesture classifier on recorded landmark fixtures (hit rate and false triggers); arming and cooldown logic; the camera never runs when disabled, in sleep or with the privacy switch off; no frame is written to disk (test by scanning the data folders); the serial and Wi-Fi protocols including replay and bad-signature rejection; device-offline behaviour; allowlist enforcement. Run the full suite.

DO NOT: store or send camera frames; bind a risky action to a gesture; expose the hardware link beyond the LAN; require the board for anything else to work.

DELIVER: files changed; the measured gesture false-trigger rate; firmware, parts list, wiring and flashing steps; what is left.
```
