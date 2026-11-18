# Phone observations and tentative patterns

Phone signals are observations, never proof of intent or a habit. Everything here runs locally without a language model. Laptop-only learning and its evaluated predictor artifacts keep their existing inputs. The new prediction adapter reuses the counting Predictor and learner feature extractor on a separate, source-backed cross-device view.

| Pattern | What is measured | How it can be wrong |
| --- | --- | --- |
| Next app across devices | Chronological app intervals; hour, weekday, place, previous app and device weight frequency counts. Predictions are rebuilt from retained source data, not promoted into the laptop model. | Missing uploads, simultaneous devices, a borrowed handset and an unusual day can make sequence order misleading. It is a guess, never permission to open an app. |
| Possible distraction | Leisure-category phone intervals during effective class/deadline windows or recent observations during the current study mode. Uses the existing personality checks and humour situation source. | Social apps may be classwork, a break may be planned, a deadline may already be complete, and Android categories can be wrong. Questions ask the owner rather than assigning intent. |
| Sleep/wake estimate | First recorded daily unlock, last preceding evening screen-off and night charging, compared alongside the daily Health Connect duration where available. | Screen-off may mean reading, TV or another device; charging may happen while awake; the first unlock may be hours after waking. Health data can itself be incomplete. No inferred sleep is inserted into confirmed temporal memory. |
| Place routine | Home-leave to college-enter observations grouped by departure hour; frequency weights halve after 14 days. | Geofence delivery is delayed, permissions may be revoked, place names can be inaccurate, and going somewhere does not establish purpose. Sparse evidence stays unreported. |

Each candidate becomes a raw `phone_pattern` thought carrying its handset and pattern key, an uncertainty statement and surprise strength. The existing 20-hour repeat guard applies. Explicit day review/learning asks one local question through the existing pending-question flow; an answer is stored as that pattern's owner-provided reason. Silence, a prediction, or a category is never counted as confirmation. Unknown Android packages use the shared `knowledge`/owner-teaching flow with device-namespaced keys; local metadata/rules precede any optional teacher.

The read-only timeline selects the authoritative privacy-aware laptop plugin when installed (never silently falling back to legacy private-title logging), plus phone app intervals. It clips ranges, resolves same-device overlaps, keeps two devices' overlaps, and labels missing observations rather than fabricating activity. “Screen time” briefings use recorded app intervals as a proxy, not a complete OS screen-time report. Multiple phones retain device IDs. Attention uses fresh screen/unlock/motion evidence and laptop idle time, ages stale evidence out, and debounces bus changes for 30 seconds. Night charging with screen-off is only an asleep estimate. Neither estimate grants automation authority.

Phone app names/reasons stay out of default model wording, inquiry evidence, semantic indexing and chat history. Phone questions and replies bypass generic semantic answer learning. Briefing lines contain durations/categories/first-unlock time, not apps. Raw phone data never enters `cognition_context.live_state()`; life-state receives only coarse attention/confidence. Telegram phone recaps are off by default. The local `services.phone_signals.preferences.update()` API persists explicit boolean settings `ai_app_names`, `teacher`, and `telegram_briefings` in `memory/phone/preferences.json`; defaults are false. The optional app-identity teacher requires both name-sharing and teacher switches, and still stages an owner-confirmed proposal. Timeline and offline query wording stay local even when model wording is enabled.

Queries: “what am I using on my phone”, “how long was I on Instagram today”, “which device have I used more today”, “when did I last use my phone”, and “what did I do after class”. Replies report recorded evidence and freshness; they do not claim live foreground state from stale uploads. The signed safe `/remote/v1/timeline` endpoint and PWA Timeline screen show today’s two lanes. It uses the normal approved-owner gate; `phone_data` remains the separate upload permission, so an owner’s PWA can read their Android companion observations despite having a different signing key.

Forget deletes the handset’s P2 source events/heartbeat and its namespaced thoughts, reasons, knowledge/proposals, idempotency ledger and pending phone question. Cross-device predictions have no persistent artifact: the next read rebuilds them solely from remaining intervals. Laptop-only model files are untouched. No new semantic index, external service or model dependency is added. The three isolated implementation checkouts under `tasks/p3-*-wt` were created for coordination and deliberately retained; agents hit their usage limit without editing them.

## Using it and validation

Restart FRIDAY after this source update, enable remote locally again, and open **Timeline** in the PWA. Ask the offline queries above, or say **ask me about my day** to review one local candidate. A reason is stored only when you answer. Forget also rebuilds the shared learned-category cache from remaining knowledge; voice answers use the same private path, with local-only speech.

Full-suite coverage plus isolated Tk retry and final targeted checks reconciled to **7,205 unique Python cases passed, 13 skipped** (plus 7 passing subtests). The full run had eight transient Tk setup errors; its settings-window retry passed all12 tests. Final privacy/cache/voice/learning/remote/PWA checks passed **113** tests. JavaScript: **36 passed**. PWA build and 360px Timeline smoke passed. Full-run inputs and post-run changes/rechecks are explicitly recorded in `tasks/phone-learning/handoff-receipt.json`; it does not claim the later cache/voice fixes were part of the earlier full-run source snapshot. Screenshot: `tasks/remote-pwa/timeline-360.png`.

Remaining validation is real-phone timing, category accuracy, and sleep/place calibration. Signals and predictions are intentionally incomplete evidence, not a complete account of a day. No live owner data, production restart, commit or deployment was used for validation.

## Files changed (34)

| Area | Files |
| --- | --- |
| Activity | `services/activity/timeline.py`, `attention.py`, `phone_commands.py`, `categories.py` |
| Mind | `services/mind/phone_patterns.py`, `knowledge.py`, `app_learning.py`, `talk.py`, `training.py`, `wording.py`, `reasoning_store.py`, `life_state.py` |
| Private text/voice routing | `interfaces/api/routes/chat.py`, `voice.py`, `services/automation/intent.py` |
| Receiver/settings/API | `services/phone_signals/remote.py`, `preferences.py`, `services/remote/routes.py` |
| Briefings/runtime | `services/proactive/briefing.py`, `watcher.py`, `plugins/briefings/content.py`, `services/telegram/summaries.py` |
| PWA source | `island/remote/app.mjs`, `index.html`, `style.css` |
| Generated shell | `island/remote-dist/app.js`, `index.html`, `style.css`, `sw.js` |
| Tests | `tests/test_phone_timeline.py`, `tests/remote/test_timeline.py`, `tests/remote/test_pwa_browser.py`, `tests/conftest.py` |
| Documentation | `docs/PHONE-PATTERNS.md` |
