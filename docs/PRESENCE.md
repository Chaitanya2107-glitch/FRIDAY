# P5: presence, reviewed scenes and notification triage

Presence is a local estimate, not verified attendance, a diagnosis of sleep, or permission to act. The engine combines one consented handset's place/motion/screen/charging metadata with laptop idle time and the effective timetable. No model is needed. Raw notification content and physical place data do not enter AI context or chat history through this feature.

## Turn it on and try it

1. Update the Android app with `android/app/build/outputs/apk/debug/app-debug.apk`. Its debug certificate matches P4, so an update preserves pairing. [Android build/install instructions](../android/README.md) cover Studio and `adb install -r`.
2. Restart FRIDAY after the source update, enable remote locally, and keep Tailscale connected. Enable only the Android signals you want. Places, motion, screen and battery improve presence; each retains its existing explanation and permission flow.
3. Ask **where am I**. With phone signals available, **what mode am I in** also reports the presence estimate. With no phone signals, the existing laptop-only mode answer stays compatible. The PWA Home and the small phone badge by Mochi show the same estimate; offline PWA values say Last known.
4. Try **when I reach college start class mode**, **when I leave home tell me what is due today**, or **at 11 pm start sleep mode**. Read the full parsed preview and answer Yes to save. No executes nothing; a changed scene hash requires review again.
5. In Android's **Presence and notification controls**, notification snoozing and phone DND/ringer control both start OFF. Their explanations appear before the relevant Android access screen. VIP/urgent package lists are short and empty initially. Turning on mode control does not turn on a signal collector.

Ask prompts and rule-definition review remain laptop-owned. They do not add a remote scene-approval bypass to P0. If the owner is away or attention policy blocks an interruption, an Ask rule can be withheld rather than acted on. A safe rule that has earned and received explicit Do and tell approval can run away from the desk with fresh consented phone signals. Quiet settings, active exchanges and shared budgets still apply. An unanswered or expired prompt never counts as acceptance.

## What the estimate means

| State | Main evidence | How it can be wrong |
| --- | --- | --- |
| `at_desk` | Laptop input within three minutes | Someone else may have used the laptop. |
| `on_phone` | Unlocked screen, motion state and idle laptop | The phone may be unlocked without active use. |
| `in_class` | College place and a current effective class window | Being on campus does not prove attendance. |
| `commuting` | In-vehicle motion, or walking outside a named place | A car trip may not be a commute; a geofence can be late. |
| `at_college_free` | College place without a scheduled class | A cancelled/imported timetable may be incomplete. |
| `at_home` | Home place without stronger activity evidence | The phone may have been left at home. |
| `away` | No desk input or no suitable known place | A library or other named place may not fit the finite categories. |
| `winding_down` | Late home inactivity or explicit sleep scene | The owner may still be awake and busy elsewhere. |
| `asleep` | Night charging, screen off, laptop idle, sustained dwell | These are proxies, not Health Connect-confirmed sleep. |

State changes normally need 45 seconds of consistent evidence and at least 60 seconds in the prior state. Commuting needs 60 seconds; sleep needs five minutes. Place edges have a separate 45-second debounce. Startup/reconnection baselines do not invent arrivals. A stale/missing heartbeat, disabled signal or revoked handset loses authority; stale data cannot satisfy automatic rule checks. Different handsets' screen/place/motion signals are never combined into one observation.

## Rule definitions and trust

Rules live in the scenes plugin's private data directory as `presence-rules.json`. The grammar handles the examples above. Advanced definitions can add `conditions` with `days` (`daily`, `weekdays`, `weekends`, or `mon`…`sun`), an `after`/`before` HH:MM window (including overnight), and `in_class` for a scheduled class window. Presence triggers support `arrive`/`leave` a place and `enter_state`/`leave_state`. Finite actions are `start_scene`, `show_card`, `phone_notice`, `phone_mode`, and `read_due_today`. Unknown fields and arbitrary commands are refused.

Edit an existing definition for advanced actions/conditions rather than forging a confirmation marker. A changed definition or scene hash invalidates approval and returns the rule to Ask. Catalog presence triggers also need a rule preview/Yes; `auto:true` cannot bypass this path.

- **Ask:** every new rule starts here. Saving approves the definition; matching occurrences still require a fresh Yes. Scene first-use/changed-file approval remains separate.
- **Three consecutive successful accepts:** FRIDAY offers once to switch that rule to **Do and tell**. Ignoring or declining that offer never elevates it.
- **Do and tell:** only a confirmed, unchanged, safe rule can run. Actions are revalidated against current evidence and attention policy, with a durable running receipt written before effects and undo tokens checkpointed afterwards.
- **No or Undo:** returns the rule to Ask and resets its streak. **undo that** only owns a recent presence receipt, not an unrelated action.
- **Risk cap:** nested app opens/closes, unknown/custom command effects, phone interruption-mode changes, and other confirm-risk effects stay at Ask. The stock class scene opens College Schedules, so it cannot be promoted. This does not weaken the P0 registry or generic remote-origin event restrictions.

Scene exit also releases phone modes belonging to that run. Restoration checks ownership and preserves later manual phone changes. Already-spoken words or an already-read notice cannot be recalled; receipts state that. Failed restoration keeps recovery information, and the phone's independent expiry path remains available.

## Budgets and anticipation

P5 uses a narrowly scoped deterministic extension of the existing executive review, sharing its actual attempt table: at most **four reviews per hour**, at least **five minutes apart**. Ask/promotion questions also share the existing **three-per-day, 45-minute-gap** interruption budget. Disabling nudges, pausing conversation, quiet mode, applicable quiet-hour preferences, active calls, speaking/listening, pending replies and attention restraint can withhold delivery. Do and tell does not grant permission to bypass those controls. Urgent VIP/call/alarm notices still retain the shared budgets.

The model review path is unchanged for other features. Presence does not enable reasoning or make a model call. Local decision records use generic metadata and hashed keys, not notification text or physical-location descriptions.

Commute hints use P3's existing home→college observations, a 14-day half-life weighted duration estimate, at least three observed travel days, and an affirmative owner-confirmed routine. Every hint says its basis and receipt time. Study timing uses an existing accepted study habit. Due-tomorrow hints cite the stored deadline and recorded current availability; lack of a record does not establish lack of other plans. Optional anticipation and greetings stay silent in study, exam, class and sleep contexts. A home/college greeting can occur once per observed arrival, using the existing mood event and delivery budget.

## Example day

This assumes fresh signals, an effective 09:00 class, an owner-confirmed ~30-minute commute estimate, available notification budgets, and no overriding quiet/pause setting. Other activity may legitimately cause silence.

| Time and evidence | Estimate | What FRIDAY does |
| --- | --- | --- |
| 07:20: first unlock; laptop idle | On phone | Shows the estimate. Initial sync is a baseline, so no invented arrival greeting or scene run. |
| 08:20: laptop active at home | At desk | “As of 08:20, leave in about 10 minutes for your 09:00 class.” It cites the observed trips and owner confirmation. |
| 08:31: home exit and vehicle motion persist | Commuting | Publishes the debounced state. An unaccepted leave-home rule cannot read anything out; blocked Ask prompts do not run silently. |
| 08:56: college entry stabilises; laptop is in use | At desk, then in class at the scheduled time | Offers “Start class mode?” after current-source/budget checks. Yes may first open the scene's full first-use preview. The app-opening class scene remains Ask even after three accepts. |
| 09:00–10:00: class context | In class | Scores package/category/importance metadata. Calls, alarms and marked VIP/urgent apps bypass snoozing. With snoozing OFF, Android notifications remain visible normally. No notification text is collected. |
| 10:00: class mode/window ends | College free | When quiet/attention budgets permit, offers a private digest such as “12 notifications — 3 chat, 5 shopping, 4 other.” Opening/dismissing later teaches the original posting situation once. |
| 11:00: working on the laptop in the library | At desk | The finite state does not pretend the library is the classroom. A library place rule can be defined explicitly; it still requires review and Ask acceptance. |
| 12:15–12:40: a focus timer runs and ends | Study context over the physical estimate | Holds optional anticipation/greetings. On exit, refreshes the phone policy and stops snooze renewal; Android restores leased notifications. |
| 18:20: a genuine home arrival stabilises | At home or on phone | One short welcome, if eligible, and a brief happy Mochi mood. It can use the consented companion when the owner is away from the desk. |
| 19:00: home, no current class/focus, lab record due tomorrow | At desk/home | A bounded local hint cites the deadline and current records; it does not claim the owner has done no work. |
| 23:00: explicit sleep rule matches while the owner is awake | At desk/winding down | Asks before the sleep scene unless it has separately earned safe Do and tell. Quiet settings or an exhausted budget can withhold it. |
| Later: charging, screen off and idle persist | Asleep estimate | Keeps optional notices silent. It does not report the proxy as verified sleep. |

## Notification privacy and Android limits

P2's old `{package,time,category}` payload remains valid. Optional lifecycle fields are an opaque salted `notification_id`, `event`, removal `reason`, and `importance`. Raw Android notification keys/tags and extras never cross the wire. Opened means Android reported `REASON_CLICK`; dismissed means user cancel/cancel-all. App cancellations, timeouts, grouping, snoozing and other removals are neutral. An open that does not remove the notification is not observable through this API.

Each app/situation has a local Beta belief, with nightly decay toward the existing humour prior. Dedupe prevents updates or snooze re-posts from inflating counts. Delayed events with no recorded historical context remain unknown rather than being assigned a fabricated situation. Forget phone data removes notification rows, learned beliefs and derived presence/rule history while retaining explicit owner-authored rule definitions.

Snoozing is **OFF by default** and separately explained. It never applies to calls, alarms, ongoing/foreground-service notifications, high-importance notifications, VIP/urgent apps or FRIDAY itself. The public listener API has no early unsnooze operation: P5 uses Android-owned snoozes of at most ten seconds and stops renewing on exit, pause, stale/disconnected policy, Forget or service shutdown. This means restoration is timed, not instantaneous. Snoozing happens after posting and cannot guarantee prevention of an app's initial alert sound. See the [Android listener API](https://developer.android.com/reference/android/service/notification/NotificationListenerService).

DND/ringer control is another default-OFF grant. On Android 15+ it controls FRIDAY's own Zen rule, not the owner's global DND policy. Older releases use compare-and-restore ownership. Recovery tokens survive interruption; the foreground ticker and non-exact alarm retry restoration. Revoked permission or OS scheduling can delay recovery, and the app reports a pending restoration instead of claiming success. See [Android NotificationManager](https://developer.android.com/reference/android/app/NotificationManager).

## Files, builds and remaining checks

The exact P5 source list is [PRESENCE-FILES.md](PRESENCE-FILES.md). Earlier uncommitted P3/P4 changes remain intact. Evidence is under local `tasks/presence/`; screenshots include the 360 px PWA and island badge.

Validated on 2026-11-16: the full Python suite passed **7,332 tests plus seven subtests**, with **13 skipped and zero failures/errors**. Source inputs remained unchanged for the entire run. The initial full run caught two reminder-routing regressions; these were fixed and the entire suite was rerun successfully. **45 JS tests** and both frontend builds passed. **25 Kotlin/JVM tests** passed, including actual Room/Robolectric tests; APK assembly passed and Android lint reported **zero errors and 40 warnings**. The Windows island debug build also passed. No live production automation or physical phone was exercised.

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`, SHA-256 `9be829d0803972feeb5f0daf2ae3d8bf56abd32cc10cc4a448206cb6cd92c0b7`. Its debug signing certificate matches P4. The Windows island is `island/src-tauri/target/debug/friday-island.exe`. Frontend builds include the updated PWA shell and island assets. Load the updated FRIDAY sources when ready, then enable remote locally again; P0 intentionally turns remote off after a source update.

The 360 px previews are [PWA Home](../tasks/presence/pwa-home-360.png) and [island presence badge](../tasks/presence/island-360.png), using synthetic API fixtures. Local `tasks/presence/handoff-receipt.json` binds source hashes, complete Python XML results, native reports, screenshots and both executable artifacts. The supplemental CLI code-pattern scan only covers JS/TS, not Python/Kotlin/MJS; its two fixed-SVG `innerHTML` findings were reviewed. Receiver/schema tests and manual boundary review supply the primary evidence for privacy and authority checks.

Physical-device checks remain: real geofence/motion timing, removal-reason behaviour in your apps, OEM snooze timing and initial alert behaviour, DND/ringer ownership and restoration after process termination, and foreground-service reliability. Automated tests use synthetic days and fake hardware; no owner notification content, real places or production automations are used.
