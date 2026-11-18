# P4: handoff, waiting actions and phone approvals

P4 adds a native companion channel alongside the existing KDE Connect integration. It uses the same owner identity, Tailscale HTTPS origin, non-exportable transport key, signatures, nonce checks, scopes, audit log and local kill switch as P0. No Firebase or third-party relay is used.

## Start here

1. Build/install the debug APK using [the Android instructions](../android/README.md). Update the existing installation with the same debug signing certificate to preserve pairing and the Room database.
2. Restart FRIDAY after updating its sources. Locally enable remote access; source updates intentionally turn P0 off. Pair the Android app if needed and approve the `phone_data` scope on the laptop.
3. In Android, enable **Keep connection with signals off** and allow its visible notification. All sensor toggles can remain OFF. Keep Tailscale connected on both devices.
4. On the laptop, say **companion phones**. If more than one native phone is paired, say **use companion phone NAME_OR_ID**.
5. Open the existing PWA, or refresh it to install the updated app shell. Public Tailscale paths are `/app/` and `/v1/…`; signatures always use `/remote/v1/…`.

## Try each feature

| Feature | Test with your phone | Expected result |
| --- | --- | --- |
| Phone → laptop text | Share a note to **Share to FRIDAY**, review, then Send | Laptop clipboard history gains a `source=phone` entry. The system clipboard is unchanged. |
| Phone → laptop link | Share an HTTP or HTTPS link | Laptop asks whether to open it. Say **open phone link**, then approve locally. Receiving a link never opens it automatically, including during focus/study. Other schemes are only inert text. |
| Laptop → phone note | Say **send note Take a break to my phone** | A phone notification offers Open; tapping shows the note. Copying it requires another explicit tap. |
| Browser handoff | With a supported browser in front, say **send this URL to my phone** | One explicit address-bar read sends its HTTP(S) URL. No page text or clipboard read is needed. |
| Clipboard handoff | Laptop: **send clipboard to my phone**. Phone: open **Review and send current clipboard**, or add the FRIDAY Quick Settings tile | Clipboard reads on Android happen only after opening the visible review screen and tapping Read. There is no background clipboard listener. |
| Phone → laptop file | Share a small PDF or text file, then Send | SHA-256-checked file lands in `Documents/FRIDAY-from-phone/` with an opaque ID prefix. It is never opened. Try sharing `../a.txt`, an executable or a file over 100 MiB: it must be rejected. |
| Laptop → phone file | Say **send file C:/Users/you/Documents/example.pdf to my phone** | Tap the phone notification, then Download. Verified bytes go to **Downloads/FRIDAY**; no file viewer launches. |
| Waiting actions | Disconnect the laptop, tap Focus 25 or Ring laptop in the PWA, or send a native note. Reconnect | Visible waiting rows survive reload/restart, send oldest first and expire after 15 minutes by default. The PWA allows up to 24 hours. Cancel works before sending. |
| Confirm-risk offline | Disconnect, then try Lock PC | It cannot enter the queue. Chat also never queues. |
| Find phone | Put the phone on silent and say **ring my phone** on the laptop | Alarm-stream sound runs for up to 30 seconds, with a Stop notification. Previous alarm volume is restored. The reply includes last reported place, battery and last seen; unavailable signals say unknown. |
| Find laptop | Tap **Ring my laptop** in Android or **Ring laptop** in the PWA | Laptop beeps and displays a local toast. The phone receives its last active app and idle time. |
| Phone approvals | Android: Set up phone approvals; approve key enrollment on the laptop. Then locally say **enable phone approvals** | A fresh strong biometric is required to sign each approval. Try a laptop installer deletion or message send, answer Yes locally, then accept or deny on the phone. Denial stops it. Expiry/unreachability leaves a laptop confirmation fallback. |
| Forget | Use Android's existing Forget phone data flow and its P0 PIN confirmation | Pending commands, inbox and staging files are wiped locally; laptop signals, derived learning, outbox, approval keys and tracked unmodified quarantined files are removed. Existing command receipt hashes remain briefly to prevent re-execution. |

## Explicit opt-ins

**enable phone clipboard sync** enables laptop → phone sync using already-read smart clipboard snapshots. It never adds another clipboard reader. Private flags, password-manager ownership and conservative content checks exclude secrets, keys, tokens and verification codes. The option starts OFF. **disable phone clipboard sync** stops it. Phone → laptop clipboard sync always remains explicit.

**enable phone file indexing** removes the quarantine `.nosearch` marker and adds its root to the installed semantic search plugin. It starts OFF; broad Documents indexing cannot include the quarantine while the marker is present. **disable phone file indexing** restores the exclusion. The existing indexer removes excluded entries on its next pass and rechecks exclusions before reading files.

**enable phone approvals** starts OFF. The hook covers existing confirmation-driven installer deletion, file organising, WhatsApp/KDE message sends, mode/personality setting commands, companion settings and native customization CRUD (contacts, routines, projects, modes and screen-app grants). It does not replace P0's PIN confirmation, authorize arbitrary remote settings, or unlock Windows. The phone result only releases the waiting laptop executor; it never initiates an action itself.

## Transport and failure behaviour

- Native inbox: signed GET `/remote/v1/phone/inbox`, 30-second wait, reconnect/backoff; phone commits Room receipts before signed POST `/phone/ack`. Message types are `text`, `link`, `file`, `ring`, `approval`. Each is addressed to exactly one current device and expires within 24 hours. Ring and approval requests expire after one minute.
- Safe waiting actions: signed POST `/remote/v1/queue` contains a stable ID, creation/expiry times, command and arguments. Both client and current server registry enforce safe risk. Supported queued effects are focus start/stop, reviewed safe scenes, adding a note, ringing the laptop and native text handoff. Receipts are recorded **before** execution. A crash in the execution window produces **uncertain**, never an automatic retry; check laptop activity before issuing a new action.
- Files: `phone/file/begin`, `chunk`, `finish`, `read` are allowlisted and require `phone_data`. Only basename metadata and opaque IDs cross the wire; no phone-supplied path is accepted. Limit is 100 MiB per file. Script/executable extensions, dangerous double extensions and executable signatures are rejected. Uploaded bytes are never extracted or run.
- P0's **16 KiB request cap and 30 requests/minute/device remain unchanged**. Files use 10,000-byte chunks and paced signed requests. A 100 MiB file can take many hours, especially alongside signal traffic. Use small files for the initial test. Native uploads resume; interrupted downloads remove their partial MediaStore entry and can be retried before expiry.
- Outbox and receipts live in `memory/phone/transport.db`, with SQLite secure deletion enabled. Text is handoff payload, never audit/chat content. File audit records contain the SHA-256 digest. Expired messages cannot be delivered; payload cleanup occurs on subsequent transport activity. Completed-upload metadata remains so later Forget can find quarantined files. Owner-edited files are preserved instead of deleted by a stale hash receipt.
- Biometric signatures bind a one-use challenge, device, action digest, expiry and remote epoch. Enrollment/replacement requires protected laptop consent and invalidates old challenges. The separate Android approval key requires authentication per use. The server does not verify hardware attestation: its trust starts with that explicit local enrollment. Strong biometric support is required; otherwise use the laptop fallback.

## Changed files

| Area | Files |
| --- | --- |
| Laptop transport | `services/remote/{transport_store,phone_transport,phone_files,phone_handoff,phone_approvals,companion_commands}.py`, `services/approvals.py` |
| Integration | `services/remote/{commands,routes}.py`, `services/automation/{intent,actions,clipboard_history}.py`, `services/customization.py`, `services/phone_signals/remote.py`, `interfaces/api/routes/{chat,voice}.py` |
| Clipboard privacy | `plugins/smart_clipboard/{privacy,main}.py` |
| PWA | `island/remote/{queue,app,transport}.mjs`, `index.html`, `style.css`, rebuilt `island/remote-dist/{app.js,index.html,style.css,sw.js}` |
| Android core | `android/core/src/main/kotlin/dev/friday/core/{BatchSender,CommandQueue}.kt`, `android/core/src/test/kotlin/dev/friday/core/CommandQueueTest.kt` |
| Android Room | `android/app/src/main/java/dev/friday/companion/{PhoneDatabase,CommandRow,HandoffDao,InboxRow}.java`, `android/app/src/test/kotlin/dev/friday/companion/RoomBufferTest.kt` |
| Android runtime/UI | `android/app/src/main/kotlin/dev/friday/companion/{MainActivity,Repository,Settings,SharingService,Alarm,ApprovalKey,Handoff,HandoffActivity,HandoffControls,ShareActivity,Transfers}.kt` |
| Android setup | `android/app/src/main/AndroidManifest.xml`, `android/README.md` |
| Tests | `tests/remote/{test_companion_transport,test_pwa_browser}.py`, `tests/test_companion_controls.py`, `island/tests/remote-queue.test.ts`, Kotlin core and Room tests |

P3's pre-existing uncommitted changes are retained separately in the working tree. P4 does not edit KDE Connect transport or expand the P0 arbitrary-action allowlist.

## Remaining device checks

Validation completed: **7,266 Python tests passed, 13 skipped, seven subtests passed; 42 JavaScript tests passed; 16 JVM tests passed.** The 360 px PWA smoke passed against the final bundle, including offline persistence, cancellation and reconnect. APK assembly and signature verification passed; its certificate matches the existing P2 debug app. Android lint reports zero errors and 31 warnings. The final PWA gateway-outage handling was checked after the full Python run with its JavaScript tests and browser smoke. Exact source/report/artifact bindings are in `tasks/phone-handoff/handoff-receipt.json`.

Build/install steps and the permission table are in [android/README.md](../android/README.md). The debug APK is `android/app/build/outputs/apk/debug/app-debug.apk`. The latest phone-width screenshots are `tasks/remote-pwa/home-360.png` and `tasks/remote-pwa/offline-360.png`.

Automated tests use synthetic data and fake APIs. Run the table above on your physical handset to verify its biometric/StrongBox behaviour, silent-mode alarm, foreground-service longevity and Android share providers. OEM battery management and user Do Not Disturb alarm policy can affect delivery. A production-signed release and on-device instrumentation are not part of this debug handoff.

Platform references: [auth-per-use biometric CryptoObjects](https://developer.android.com/reference/android/hardware/biometrics/BiometricPrompt.CryptoObject), [Quick Settings activity launch](https://developer.android.com/reference/android/service/quicksettings/TileService), and [scoped storage](https://developer.android.com/training/data-storage/shared/media).
