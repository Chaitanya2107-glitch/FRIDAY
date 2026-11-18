# FRIDAY Android companion

A native Kotlin/Compose app for sending **only the signals you choose** to your FRIDAY laptop over Tailscale. No Google-account login, Firebase project/backend, analytics product, ads, cleartext transport, or cloud receiver is used. Every signal starts **OFF**. Existing KDE Connect integration is unchanged.

## P5 presence, triage and reviewed phone controls

**Presence controls** is below the existing sharing/handoff controls. Both new switches start OFF. Keep the existing visible companion connection running to receive laptop policies. Enabling phone controls does not enable any sensor sharing. Rules must first be parsed and confirmed on the laptop; phone DND/ringer effects remain at the laptop's Ask trust level.

- **Notification metadata** now includes a salted opaque notification ID, Android importance and an event/removal reason. Posted notifications are deduplicated across updates. A removal due to click reports `opened`; user swipe/clear-all reports `dismissed`; system/app removals are neutral. Opens which do not remove a notification are not observable through Android's listener. FRIDAY never reads ordinary notification title/text/extras, including when a local content preference exists. KDE Connect's separate private notification path is unchanged.
- **Allow reviewed DND / ringer changes** first explains the access, then opens Android's Notification policy settings if needed. Each signed mode request checks local consent, a current connection, the live Android grant, an expiry and an opaque restoration token. Recovery information is saved before the effect. Undo, pause, Forget, disconnection and service shutdown restore FRIDAY-owned changes. Manual owner changes win. A service ticker and a non-exact AlarmManager recovery wakeup retry expired changes after process interruption; Android scheduling/permission revocation can delay recovery. **Restore phone modes now** is always available. On Android15+ FRIDAY controls its app-owned Zen rule and cannot override the owner's global DND setting.
- **Snooze low-score notifications in focus** first explains notification-listener access, then requests it only if missing. It also requires the separate Notification metadata signal to be ON and a fresh signed study/class policy containing low-score packages. Calls, alarms, important channels, system notifications, ongoing/foreground-service notifications and VIP/urgent apps always pass. VIP and urgent lists start empty, are capped at ten app packages each and never authorize notification content.
- **Restoration limit:** the public Android listener API supports timed snoozes but no public early-unsnooze operation. FRIDAY therefore uses **10-second snooze leases**, renewed only while the reviewed focus policy and local collection/consent gates remain active. After the phone receives the context exit, disconnects, pauses, or the policy expires, Android restores the notification within the current ten-second lease, even if FRIDAY is killed. Policies expire within two minutes unless renewed. There is no hidden API, notification cancellation, cloning or reposting. Because the listener runs after a notification is posted, it cannot guarantee suppressing the initial sound; DND is a separate explicit grant.

Additional P5 permission:

| Permission | Purpose | How it is granted |
| --- | --- | --- |
| `ACCESS_NOTIFICATION_POLICY` | Apply and restore explicitly reviewed phone DND/ringer changes | OFF by default. The explanation appears after turning on the control toggle, before Android's special-access screen. Checked again for every effect. |

Phone checks: leave both switches off and confirm that normal notifications and DND are untouched; enable metadata, open and dismiss a few notifications, and inspect metadata-only sent receipts; enable snoozing, enter a reviewed study rule and verify a low-score test app returns within ten seconds of exit/pause while a VIP/call/alarm stays visible; grant phone mode control, approve a laptop rule, then undo and manually change the mode to check ownership preservation. Force-stop/reopen and verify durable recovery. These device/OEM behaviours need physical-device verification; JVM tests cover policy gates, outcome mapping, VIP bypass, lease expiry, token-bound undo and manual-change preservation.

P5 build validation: **25 JVM tests passed**, including real Room/Robolectric tests; debug APK assembly passed, and Android lint reported **zero errors and 40 warnings**. The APK's signing certificate matches P4 for an update that preserves pairing. Its SHA-256 is `9be829d0803972feeb5f0daf2ae3d8bf56abd32cc10cc4a448206cb6cd92c0b7`. Source, test-report and artifact bindings are in local `tasks/presence/native-receipt.json`. The [presence guide and example day](../docs/PRESENCE.md) cover laptop-side rules, budgets, privacy and remaining hardware checks.

Official platform references: [notification listener callbacks and timed snoozes](https://developer.android.com/reference/android/service/notification/NotificationListenerService), [DND policy access and Android15 app-owned rules](https://developer.android.com/reference/android/app/NotificationManager).

## P4 handoff, waiting commands and approvals

Turn on **Keep connection with signals off** to receive laptop messages, rings and approval requests while every signal stays OFF. Enabled signals already keep their connection running; this switch extends it to when signals are off. It uses the same visible foreground service and signed 30-second long-poll over the paired laptop's HTTPS Tailscale origin. A disconnected laptop produces a visible waiting message and exponential reconnect backoff. The switch is OFF by default; no boot receiver starts the connection.

- **Share to laptop:** In another app choose Android's Share button, then **Share to FRIDAY**. Review the text/link or file and tap **Send to laptop**. Text goes to smart clipboard history; links wait for an explicit laptop Open action. Files are copied to a private phone buffer first, then delivered to laptop quarantine, never opened. Script/executable filenames, double executable extensions, hidden/reserved Windows names and paths are refused. The file limit is 100 MB, with at most two waiting files.
- **Clipboard:** Add **Send clipboard to FRIDAY** from Android's Quick Settings tile editor, or tap **Review and send current clipboard** in the app. The tile opens a visible screen; tap **Read current clipboard**, review it, then send. There is no clipboard background reader or automatic phone-to-laptop clipboard sync. [Android restricts clipboard reads to focused apps.](https://developer.android.com/privacy-and-security/risks/secure-clipboard-handling)
- **Receive from laptop:** A private notification has an **Open** action. Notes are displayed first and copied only with **Copy note**. Links need **Open link in browser**. Files need **Download file**, are SHA-256 verified and saved in **Downloads/FRIDAY**, and are never automatically opened. Partial failed downloads are removed. Keep the connection running and this screen open during a download.
- **Waiting commands:** The native app queues only the reviewed safe commands `ring_laptop`, `phone_handoff`, `start_focus`, `stop_focus`, `set_scene` and `add_note`. Each has its own ID, durable Room row, creation time and 15-minute expiry. The core supports explicitly bounded lifetimes up to 24 hours. Confirm-risk actions never enter this queue. Reconnect sends oldest first; lost replies reuse the same ID. Completed/refused/expired/uncertain receipts remain visible and can be dismissed. An uncertain receipt is never retried. **Cancel waiting action** removes the local row; it cannot undo a command already received by the laptop.
- **Files while offline:** The private outgoing copy and offset survive process restarts, with a 24-hour expiry. Resume the connection to continue. P0's 16 KiB request cap and 30 requests/minute remain unchanged; 10,000-byte signed chunks are globally paced, so a 100 MB transfer can take more than seven hours and interruptions can make it expire. This is intentionally not a bulk-sync replacement.
- **Find laptop:** Tap **Ring my laptop**. Its safe command waits when offline, then records a receipt with last active app and idle time. From the laptop, **ring my phone** sends a 30-second alarm at full alarm-stream volume, with a notification **Stop** action; stopping restores the previous alarm volume. Silent ringer mode does not mute the alarm stream, but a Do Not Disturb policy that blocks alarms or OEM restrictions may still prevent sound.
- **Optional approvals:** Configure a strong fingerprint/face biometric in Android first. Tap **Set up phone approvals**, read the explanation, and approve enrollment on the laptop. **Check approval setup** confirms registration. Enable the optional second factor on the laptop separately. An approval notification opens the action and summary; **Approve with biometric** authenticates a separate nonexportable Keystore key for that one signature. **Deny** can only deny, and expired/replayed responses are rejected by the laptop. The existing laptop prompt remains the fallback. These approvals never unlock Windows. See Android's [authentication-bound key documentation](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder).

The approval key is independent of the unattended transport-signing key, prefers StrongBox when available, and is invalidated when biometric enrollment changes. New enrollment requires laptop consent again. The laptop verifies possession of the locally enrolled approval key; enrollment does not provide remote hardware attestation. A phone without strong biometrics can use the existing laptop confirmation prompt.

P4 adds these normal/system-protected permissions; the full signal-permission table below still applies:

| Permission/access | Why it is needed | User control |
| --- | --- | --- |
| `USE_BIOMETRIC` | Authorize a single approval-key signature | Normal manifest permission; biometric prompt appears only after tapping Approve. |
| `MODIFY_AUDIO_SETTINGS` | Temporarily raise alarm-stream volume for Find my phone | Used only for a received, signed ring message; Stop/30-second timeout restores prior volume. |
| `BIND_QUICK_SETTINGS_TILE` on the tile service | Allows Android to bind the user-added tile | System-protected service permission, not an app runtime grant. Tile launches a visible clipboard review screen. |
| Temporary shared-content URI access | Read the specific file explicitly shared to FRIDAY | Granted through the sharing app; no blanket storage/photo permission. |

Room version 1 upgrades to version 2 without deleting earlier buffered signals. **Forget phone data** also clears waiting command rows, inbox receipts, private outgoing files and pending downloads, disables the companion connection and fences late responses. Files already deliberately saved to Downloads belong to the user and remain there.

### Phone checks

1. Install the new debug APK with the same signing certificate (`adb install -r ...`); keep pairing and all signals OFF. Pair if this is the first installation.
2. Enable **Keep connection with signals off**, allowing the explained notification permission. Turn off laptop connectivity, send two notes, and inspect **Waiting and receipts**. Reconnect: they arrive in order once; leave another offline for over 15 minutes and verify it expires.
3. Share a small PDF and confirm laptop quarantine contains it without opening it. Try `.exe`, `note.ps1.txt` and files over 100 MB: they must be refused. Interrupt a permitted transfer and resume before its expiry.
4. Send a note, link and file from the laptop. Tap each notification and its explicit action. Confirm the file appears in Downloads/FRIDAY only after checksum verification and never opens automatically.
5. Use the Quick Settings tile: no clipboard content is read until the visible **Read current clipboard** button is tapped. Check that ordinary app launch/service polling does not read the clipboard.
6. Ring the phone while its ringer is silent; tap Stop and verify previous alarm volume returns. Ring the laptop from the app and inspect its receipt.
7. Enroll the separate approval key with laptop consent. Exercise approve, deny and timeout; cancel the biometric dialog and confirm denial/fallback. Disable the phone connection and verify the laptop prompt remains available.
8. Upgrade an existing installation and verify its old signal buffer survives. Forget data with transfers waiting and verify the local buffer/queue are wiped and late responses cannot restore them.

JVM tests cover shared signing vectors, TLS retry with the same command ID, safe-only queueing, expiry/order/refused/uncertain receipts, file/link filters, actual Room persistence/deduplication and the version-1 migration. Physical-device checks remain necessary for StrongBox/biometrics, Quick Settings, OEM service policies, real share providers, alarm/DND behavior and Downloads.

P4 validation: **16 JVM tests passed** (13 pure Kotlin/core and three actual Room/Robolectric tests), debug APK assembly passed, and lint reported **zero errors and 31 warnings**. These include cancellation during a network request and expiry during queue draining. No Gradle/dependency changes or lint baseline were added. One narrowly scoped lint compatibility suppression covers the runtime-guarded API29–33 tile-launch overload: Android's [TileService reference](https://developer.android.com/reference/android/service/quicksettings/TileService) requires the PendingIntent overload from API34 and the older Intent overload before that. Both old and new APKs passed `apksigner verify`; their certificate SHA-256 digests match, allowing an in-place debug update. Source/artifact hashes and exact test-report bindings are recorded in `../tasks/phone-handoff/android-receipt.json`. No physical device was used for these claims.

## Build and install in Android Studio

1. Install current stable Android Studio. Open **this `android` folder** as the project, not the repository root. Let Studio sync Gradle. It downloads build dependencies from the normal Google/Maven/Gradle repositories; these are development downloads, not telemetry destinations.
2. In SDK Manager install **Android 17 / API 37.0** and Android SDK build tools. Use Studio's bundled JDK (17 or newer; this machine has JBR 25). The project pins AGP **9.5.1**, Gradle **9.6.0**, Kotlin **2.4.21**, minSdk **29**, targetSdk **37**. The wrapper JAR and distribution are verified against Gradle's official SHA-256 checksums.
3. Choose **Build → Generate App Bundles or APKs → Generate APKs** (the wording can vary by Studio version), or run in Studio's terminal:
   ```powershell
   ./gradlew.bat :core:test :app:testDebugUnitTest :app:assembleDebug :app:lintDebug
   ```
   On macOS/Linux use `sh ./gradlew ...`. The pure Kotlin `:core:test` task does not require an emulator. Room's actual Android database is tested on the JVM with Robolectric.
4. The debug APK is **`app/build/outputs/apk/debug/app-debug.apk`**. Copy it to your Android 10+ phone, open it and explicitly allow installation from that source; or connect USB debugging and use Studio's Run button / `adb install -r app/build/outputs/apk/debug/app-debug.apk`.
5. Install/sign in to Tailscale separately on the phone and connect it to the laptop owner's tailnet. FRIDAY itself does not ask for a Google account or your Tailscale credentials. Keep the laptop's remote gate enabled. Battery optimisations and vendor power managers can delay background work; the app explains an optional exemption before opening Android's approval screen.

This repo includes all Gradle-wrapper files. `local.properties`, build outputs, signing keys and local caches are ignored. Do not commit personal SDK paths or release keys. This is a debug/sideload build, not a Play Store release.

## Pair and choose sharing

1. Restart FRIDAY after installing the receiver changes. Locally say **enable remote**, approve, then **pair my phone**.
2. In the Android app, scan that QR with the local camera scanner, or paste the **whole QR JSON**. A camera explanation appears before its permission request; paste requires no camera access.
3. Give the phone a name and set the same six-digit PIN you will use for confirmation. The key is generated in Android Keystore using StrongBox when available, with regular Android Keystore fallback when StrongBox is unavailable. Its private bytes are never exported. The app verifies the laptop fingerprint and signed pairing-status response.
4. Approve the **laptop** prompt, which explicitly mentions the `phone_data` scope. Existing P0/P1 devices do not gain that scope automatically; pair the Android app as a new device. Pairing a PWA does not share its private key with Android.
5. Turn on each desired signal. Its explanation comes **before** the dangerous/special permission prompt. Declined permissions leave that signal off. The first enabled signal also asks for the visible, quiet sharing notification on Android 13+. No permissions are requested at launch.

If Android recreates the pairing screen while the laptop is deciding, reopen the app or tap **Check pending laptop approval**. It checks the saved Keystore identity and laptop fingerprint, without storing/reusing the QR token or PIN.

Use **Sharing now** to inspect exact, laptop-acknowledged event payloads from the last hour, including observation and send times. It paginates all results; pending rows are not called “sent”. Room saves each event before upload. Pending events survive unreachable laptops and process restarts, subject to the configured **1–7 day** retention and **5,000 total-row** cap (including sent receipts). At the cap, the oldest rows are discarded; this is a privacy/space bound, not unlimited offline history.

The visible foreground service polls foreground-app changes about every 15 seconds while the screen is on, and uploads batches every five minutes. Important screen/motion/place/audio events trigger an immediate attempt, coalesced to at most once per 30 seconds to respect P0's rate limit. WorkManager retries every **15 minutes or later**; Android does not allow five-minute periodic WorkManager jobs. Uploads are acknowledged by event ID and deduplicated on the laptop. The signal buffer stays separate from P4's safe-command queue.

**Pause everything for 1 hour** stops new collection and uploads while preserving already-buffered data. Polling and registered transitions/geofences resume when that hour expires. **Resume sharing / restart service** is also available. After the OS kills the service, collection stays stopped until you explicitly resume it; WorkManager can still retry the old buffer. No boot receiver starts sensor collection. Losing Android notification permission stops collection rather than hiding the sharing indicator.

## Signal details and privacy

| Signal | What the laptop receives | Important limit |
| --- | --- | --- |
| App usage | Package, app label, Android category number, start/end epoch seconds | Foreground changes only while screen on; no titles, pixels, typing or accessibility data. Long sessions checkpoint every five minutes. |
| Screen | on/off/unlocked and unlock count | Unlock count is cumulative for the current sharing-service session. |
| Battery | Level and charging state | Heartbeat battery is null when sharing is not enabled/running. |
| Network | Wi-Fi/mobile/offline/other, home flag, optional salted SSID hash | Home recognition is separately selected after enabling network. The name is never stored or sent; redacted/unavailable SSIDs remain unknown. No traffic/history inspection. |
| Motion | still/walking/in_vehicle transitions | Uses Play Services; no accelerometer samples or GPS readings. |
| Places | User-chosen name and entered/left | Enter coordinates manually on the phone; coordinates/radius are private local geofence configuration. No map/cloud service, GPS polling, or coordinate event fields. |
| Audio devices | Headphones/Bluetooth kind, label, connected flag | Output devices only; no microphone permission or audio capture. |
| Media | Playing app, title, artist | Separate opt-in. Uses playing media sessions through notification-listener access; paused sessions are excluded. |
| Notifications | Package, posted time, category | Never title/text/extras. A local per-app “allow content” preference list exists and starts empty; it **does not enable transmission**. The requested strict laptop schema always rejects notification content, even for a locally listed app. |
| Sleep | Local date and total sleep minutes | Read-only Health Connect daily aggregate. Missing data is not fabricated as zero. |
| Steps | Local date and total steps | Read-only daily aggregate; no routes or individual step samples. |
| Interruption | DND filter and ringer mode | Read-only; no DND-policy control permission or setting changes. |

Health Connect background reads need a separate optional, supported permission. Without it, enabled Health signals refresh while the app is visible and the sharing service is running. App categories remain Android's numbers; phone intervals are **not inserted into the laptop's foreground session store**.

Bundled ML Kit scans QR codes on-device but includes internal usage/performance transport. This app removes ML Kit automatic initialization and the DataTransport backend-discovery service from the merged manifest, and blocks non-tailnet TLS via an empty default trust-anchor set. System TLS roots are allowed only for `ts.net` subdomains; the OkHttp receiver client additionally restricts requests to the exact QR origin and refuses redirects. No user CA/debug trust bypass is enabled. ML Kit brings Firebase-namespaced component/encoding support transitively; there is no Firebase app/project, Auth, Analytics, Messaging, or cloud storage configuration. The camera opens only after consent and uses a bundled model, not a model-download endpoint.

Android/Play Services and the separately installed Tailscale/Health Connect apps have their own platform behavior. Physical-device verification is still needed for OEM power management, permission settings, StrongBox availability and actual geofence/health/motion callbacks.

## Every permission

Normal manifest permissions are granted by Android at install; dangerous/special grants are requested only after the relevant user action and explanation.

| Permission/access | Why it exists | When requested/used |
| --- | --- | --- |
| `INTERNET` | Signed HTTPS to the paired laptop | Normal manifest grant; only exact QR-origin requests, no cleartext. |
| `ACCESS_NETWORK_STATE` | Detect connectivity and WorkManager network constraints | Normal grant; signal payload read only when network toggle is on. |
| `ACCESS_WIFI_STATE` | Optional home-network hash | Normal grant; SSID read only after network toggle and explicit home selection/location grant. |
| `CAMERA` | QR scanner | Runtime prompt only after Scan → explanation → Continue. Paste avoids it. |
| `PACKAGE_USAGE_STATS` | Foreground app intervals | Usage Access settings only after app-usage toggle/explanation. |
| `POST_NOTIFICATIONS` | Persistent visible sharing notice | Runtime on Android13+, after enabling sharing and its explanation; denial keeps collection off. |
| `FOREGROUND_SERVICE` | User-started visible collector | Normal permission; no automatic sensor restart at boot. |
| `FOREGROUND_SERVICE_SPECIAL_USE` | Continuous opt-in companion sharing | Normal permission with declared subtype. Avoids misusing the six-hour-limited dataSync type. A future Play release needs its own special-use review. |
| `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` | Optional reliability exemption | Only the explicit battery-explanation button opens Android's approval screen. |
| `ACTIVITY_RECOGNITION` | still/walking/in-vehicle transitions | Runtime prompt after motion toggle/explanation. |
| `ACCESS_COARSE_LOCATION` | Android location permission flow | With precise-location request for places, or separate optional home-Wi-Fi explanation. No coarse location samples are requested. |
| `ACCESS_FINE_LOCATION` | Named geofences / optional SSID identity | Runtime after the relevant explanation. No `getCurrentLocation`, GPS subscription or coordinate upload. |
| `ACCESS_BACKGROUND_LOCATION` | Named-place transitions while app not visible | Separate Android Settings explanation after precise grant. Places remains off without it. |
| `BLUETOOTH_CONNECT` | Bluetooth output-device labels | Runtime Android12+, after audio-device explanation. No Bluetooth discovery or location inference. |
| `health.READ_SLEEP` | Daily sleep aggregate | Health Connect permission screen after sleep toggle/explanation. |
| `health.READ_STEPS` | Daily step aggregate | Health Connect screen after steps toggle/explanation. |
| `health.READ_HEALTH_DATA_IN_BACKGROUND` | Optional background daily aggregates | Separate explicit Health background button/explanation; unsupported/denied means visible-app reads only. |
| Notification listener (`BIND_NOTIFICATION_LISTENER_SERVICE`) | Metadata and/or media-session discovery | System binding protection, not an app-requested dangerous permission; user enables special access after the media/notifications explanation. No extras are read. |
| `START_VIEW_PERMISSION_USAGE` on health rationale alias | Allows Android to open the Health explanation | System-protected alias, not a permission FRIDAY asks the user to grant. |
| `WAKE_LOCK` (WorkManager merge) | Finish short durable sync work | Normal permission; no custom permanent wakelock. |
| `RECEIVE_BOOT_COMPLETED` (WorkManager merge) | Reschedule existing sync work | Normal permission; does not enable sensors or start the foreground collector. |
| `dev.friday.companion.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION` (AndroidX merge) | Protect private dynamic receivers | App-signature permission; never a user grant. |

There are no permissions for SMS, calls, contacts, storage/photos, microphone, accessibility, screen capture or Health writes. Tailscale VPN traffic is excluded from API37's local-network permission, so `ACCESS_LOCAL_NETWORK` is not requested. Arbitrary LAN base URLs are intentionally rejected.

## Forget data

**Forget phone data** disables every toggle, immediately wipes Room's pending buffer and sent receipts, clears local named places/home hash/content preferences, and requests the laptop's `phone_forget` confirmation challenge. Enter your pairing PIN to complete laptop deletion. Three incorrect attempts lock approvals for ten minutes, persisted on the laptop.

If the laptop is unreachable, the phone wipe still happens and **laptop deletion pending** remains saved across restarts. Uploading and collection stay blocked until you reconnect and approve a fresh challenge. The laptop deletes only this device's events and heartbeat; other phones are unaffected. One opaque device/generation tombstone remains to prevent old in-flight batches from restoring deleted records. The Keystore identity is kept so you can complete pending deletion. Revoke the device separately to remove remote access.

## Laptop receiver / wire contract

- `POST /remote/v1/phone/events` takes `{generation, events:[{id,timestamp,type,payload}]}`. Requires the finite safe `phone_events` capability **and** `phone_data` scope. Up to 50 events, 2 KiB per payload, within P0's total16 KiB request limit. Android batches adapt to the byte limit.
- `POST /remote/v1/phone/heartbeat` takes `{battery,app_version,last_sync,signals}`; returns current generation. `GET /remote/v1/phone/status` and allowlisted `phone_status` (“phone status”) report this phone's heartbeat/settings/count. Both require `phone_data`.
- Allowlisted `phone_forget` (“forget phone data”) has **confirm** risk plus `phone_data`; it uses the existing `/commands` and `/approve` challenge/PIN path. No separate unallowlisted deletion endpoint exists.
- The current Tailscale Serve mapping exposes these as public `/v1/phone/...`; signatures always use canonical `/remote/v1/...`. The PWA Custom Tab opens public `/app/`.
- SQLite is `memory/phone/phone_events.db`, default retention30 days, purged on ingest/heartbeat/status. `PhoneStore(retention_days=...)` permits a local1–365day policy. Unknown fields/types, notification text, coordinates, oversized/invalid values and conflicting duplicate IDs fail the entire batch. Dedupe key is `(device_id,event_id)`.
- `phone.event` publishes application fields `{type,time}` only after commit, retaining the bus's mandatory `remote_origin` security metadata. It does not inject phone data into laptop activity sessions or grant action authority to subscribers.

Raw bodies, notification text, places, media metadata and PINs are never written to logs/audit. SQLite stores the opted-in data locally. `services/phone/*` and its existing KDE “phone status” command are unchanged.

## Tests and evidence

`core` JVM tests verify the shared `../tests/remote_vectors.json` canonical UTF-8 bytes and Python P1363 signatures, buffer cap/retention/acknowledgements, off/pause/forget collector gates, HTTPS-only QR origins, and an actual TLS fake-server sender (including outage/retry). The app JVM test uses **real Room with Robolectric**. Python tests cover all12 schemas, notifications/raw-coordinate rejection, scope/gate/allowlist, dedupe/atomicity, retention, confirmation and stale-generation rejection. Android lint and the full existing Python suite are run before handoff; exact results and artifact/source hashes are recorded under local `tasks/android-companion/`.

No live phone permissions, physical sensors, real health data, account logins, live production pairing or laptop-owner data are used in the tests.

Validated here on 2026-11-13: **7,190 Python tests passed, 13 skipped, and 7 subtests passed** across the entire existing suite, with normal directory-based fixture discovery. Receiver-focused tests: 35 passed. **Five core JVM tests and one real Room/Robolectric test passed.** Debug APK assembly and Android lint passed; lint reported **zero errors and 24 warnings** (style/newer-dependency suggestions and the documented battery-exemption Play-policy warning). No lint baseline or error suppression was added. Source inputs stayed unchanged during Python validation. KDE Connect files are unchanged.

## Files changed for this feature

46 source/config/documentation files; earlier P1 work is preserved:

| Area | Files |
| --- | --- |
| Android build/wrapper | `.gitignore`, `settings.gradle.kts`, `build.gradle.kts`, `gradle.properties`, `gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`, `gradle-wrapper.properties` |
| Plain Kotlin core | `core/build.gradle.kts`, `core/src/main/kotlin/dev/friday/core/{Protocol,Buffer,BatchSender}.kt`, `core/src/test/kotlin/dev/friday/core/CoreTest.kt` |
| Android build/manifest | `app/build.gradle.kts`, `app/src/main/AndroidManifest.xml` |
| Room | `app/src/main/java/dev/friday/companion/{EventRow,EventDao,PhoneDatabase}.java`, `app/src/test/kotlin/dev/friday/companion/RoomBufferTest.kt` |
| Android UI/runtime | `app/src/main/kotlin/dev/friday/companion/{AdvancedSignals,DeviceKey,Explanations,MainActivity,PairingUi,QrCamera,Repository,Settings,SharingControls,SharingService,SignalListener,SystemSignals,UsageCollector}.kt` |
| Resources/privacy | `app/src/main/res/drawable/ic_friday.xml`, `app/src/main/res/xml/{network_security_config,data_extraction_rules}.xml` |
| Receiver | `../services/phone_signals/{__init__,schema,store,remote}.py` |
| P0 integration | `../services/remote/{commands,pairing,routes,service}.py` |
| Python tests | `../tests/remote/test_phone_signals.py` |
| Documentation | `README.md`, `../docs/specs/2026-11-13-android-companion.md` |

The generated debug APK and test/lint reports are under `app/build/` and `core/build/`; final source/APK hashes, merged-permission checks and Python XML/logs are under `../tasks/android-companion/` (all local build/evidence outputs are gitignored).

Official references: [AGP9.5](https://developer.android.com/build/releases/agp-9-5-0-release-notes), [Kotlin compatibility](https://kotlinlang.org/docs/gradle-configure-project.html), [WorkManager minimum interval](https://developer.android.com/reference/androidx/work/PeriodicWorkRequest), [foreground service types](https://developer.android.com/develop/background-work/services/fgs/service-types), [ML Kit terms](https://developers.google.com/ml-kit/terms), [Android network security](https://developer.android.com/privacy-and-security/security-config).
