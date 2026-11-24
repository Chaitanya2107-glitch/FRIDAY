# FRIDAY with model assistance off

Use **Model assistance** in Settings or say “turn the model off” or “turn the model on” on the laptop. FRIDAY saves the runtime choice in `memory/model-settings.json`. An explicit `FRIDAY_LLM=on|off` is the launch-time choice. The switch covers language, vision, and embeddings. Voice recognition and synthesis keep their own settings.

## Baseline gaps and rule paths

The [call-site inventory](llm_call_sites.md) records behavior before this change. The audit also reproduced a due reminder retained with no model and a timed-out explicit memory write. The other baseline gaps below come from tracing the runtime entry points and their tests.

| Baseline behavior with the model absent, slow or invalid | Offline behavior |
| --- | --- |
| Explicit reminders could be retained indefinitely for model review. One slow review held later reminders. | The owner's original reminder and local schedule, busy and quiet checks drive delivery. Availability and routing are checked again before transport. Optional `review reminder 1` still supports an advisory model review. |
| Legacy schedule and deadline alerts waited behind optional cognition and could be swallowed by failed notification review. Merely having the alerts plugin installed could disable the legacy path. | A separate watch delivers deterministic alerts even while optional work is pending. The installed plugin takes over when its service is available. Existing focus alarms remain model-independent. |
| A dated report could wait for generation and critique, or an ambiguous relative date could never be resolved. | Calendar rules use the original receipt date and a uniquely matched timetable exam, deadline or commitment. FRIDAY previews the intended change and waits for the owner. A missing or ambiguous date or target gets a specific short question. Model-derived date proposals can be listed and confirmed separately. |
| Ordinary conversation and legacy provider errors could leave no usable reply. | Local greetings, help, owner-taught replies, saved topics, exact facts and retrieved excerpts remain available. An unclear request gets a short question. Remote replies stay isolated from laptop context. |
| A model-translated command could execute as soon as the translation passed the local parser. | In assist-only mode the local router shows the proposed command and waits for a separate yes. Explicit local rules still run directly. |
| A polished command reply could delay a finished local action. | Plain command replies are authoritative. Wording enhancement gets a short optional window and otherwise preserves the original reply. |
| Knowledge lookup could give no description. | Recognized app rules and owner-taught facts still work. An unknown app or topic can prompt for an owner explanation. A model description remains a proposal until approved. |
| Embedding failure could prevent saving an explicit memory. Semantic file search, memory recall and semantic command cache hits degraded. | Explicit memories save as text and support literal recall and exact forget. File search keeps filenames and full-text indexing. Existing vectors remain usable when model assistance returns. Lexical search remains available in the semantic-search plugin. |
| Inquiry and paraphrase review might return no result when a model could have phrased a question or related an older report. | Current source-backed goals and facts support a narrow local inquiry. Exact historical recall and saved topic references still work. Unsupported associations abstain. |
| Mixed optional notifications were withheld on any model error. | Requested reminders, schedule alerts and subsystem status have local delivery rules. Unverified or ambiguous optional nudges may remain silent. |
| Timetable image extraction, visual interpretation, browser/desktop planning, research synthesis and free-form writing require inference. | Existing saved schedules and manual class entry, local app/window observations, literal typing, authored actions and sourced research results remain available. These requests explain when the optional enhancement is unavailable. |
| Generated summaries, legacy fact extraction and richer paraphrase matching skip work on model failure. | Original reports, explicit notes, local review and category rules remain readable. Generative enhancements resume when the gateway is healthy. |

## Runtime behavior

- `providers/failover.py` is the shared gateway. It rejects off mode before provider setup. Async transport has four active slots, native embeddings have two, and callers get a bounded deadline. After three consecutive failures for a backend, the circuit holds for two minutes and then permits one recovery probe.
- `services/mind/state.py` exposes the immutable present snapshot and `explain()` provenance. The cache lasts up to three seconds. Interruption and delivery checks can ask for fresh evidence.
- `services/health/` tracks voice, desktop bridge, phone monitor, plugins and the model. Owned crashed services retry with backoff and a cap of three restarts in 10 minutes. Recovery and terminal outages use FRIDAY’s notification budgets. An idle or disabled model can stay idle.
- Say `status report` or set `daily status report at 19:30`. The report shows the current FRIDAY session, disk use, memory folder size and the latest recorded archive under `memory/backups`. The Windows phone monitor can recover locally. Handset health comes from paired contact.
- `memory/autonomy.json` keeps action levels, offers and the undo history, including existing P5 presence rules. Ask-first actions retain their confirmation fences. `undo that` uses the latest applicable receipt and checks the recorded target before compensating. Native launches without a verified process identity and messages sent through transports without retraction report that they cannot be safely undone.

## Module changes

| Modules | Change |
| --- | --- |
| `core/config.py`, `core/errors.py`, `providers/` | Persistent model mode, typed unavailability, one gateway for inference, bounded workers, circuit recovery and owned Ollama lifecycle. |
| `interfaces/settings/`, `interfaces/api/routes/`, `services/automation/intent.py` | Desktop model switch, daily report time, local chat/voice commands, and owner confirmation for interpreted commands. |
| `services/mind/date_rules.py`, dialogue, reasoning and replies | Schedule-aware date proposals, scoped clarifying questions, owner approval and deterministic replies. |
| `services/mind/state.py`, life, cognition and present-state readers | Shared immutable snapshot and field provenance. |
| `services/mind/reminder_review.py`, `services/reminders/`, `services/proactive/` | Requested reminder and schedule delivery runs from local rules. Advisory review remains available on request. |
| `services/files/`, `services/memory/semantic.py`, `plugins/semantic_search/` | Gateway-controlled embeddings, text-only owner memory, and keyword search when vectors are unavailable. |
| `services/health/`, API lifespan, bridge, voice, phone and plugin runtime | Heartbeats, capped recovery, and budgeted status notices. |
| `services/automation/autonomy.py`, presence, scenes, focus, filing and messaging | Shared levels, P5 migration, owner promotion, demotion, and validated compensation receipts. |

## Verification

Run the repository suite with `python -m pytest --llm-mode=on`, `--llm-mode=off`, `--llm-mode=slow` and `--llm-mode=garbage`. `--llm-off` is an alias for off. Tests that explicitly verify valid provider contracts keep their own model doubles in each run. Gateway integration tests exercise all four conditions, including a disposable model-process exit, timed startup, a local command, requested reminder delivery, a focus alarm and a schedule alert.

The final runtime code ran through the full Python suite in each profile on Windows. Each profile covered 7,615 regular tests and seven passing subtests.

| Profile | Passed in full run | Failed | Setup errors | Skipped | Passed after targeted reruns |
| --- | ---: | ---: | ---: | ---: | ---: |
| On | 7,600 | 1 | 0 | 14 | 7,601 |
| Off | 7,588 | 1 | 12 | 14 | 7,601 |
| Slow | 7,600 | 1 | 0 | 14 | 7,601 |
| Garbage | 7,600 | 1 | 0 | 14 | 7,601 |

The shared daily-question-budget test had crossed midnight on the test machine. Its four checks passed after the fixture pinned the attempts to the same day. The serial off-mode rerun passed all 51 Control Center and Settings tests with explicit Tcl and Tk library paths, including the 12 whose setup had failed. The runtime code stayed identical for these reruns.

## Remaining limits

- This verification uses a disposable local model endpoint and provider doubles. Installed-model latency and quality, real speech hardware, and paired handset recovery need live checks.
- Undo steps require an exact receipt and a reversible effect. Shell launches without owned process handles and messages sent through transports without retraction have limited undo. Academic edits and other actions outside the receipt-backed paths still rely on their existing history and controls.
- Backup reporting checks the most recent archive in `memory/backups`. Status reports include subsystem activity from the current FRIDAY session.
