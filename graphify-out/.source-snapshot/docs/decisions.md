# decisions.md
# F.R.I.D.A.Y — Architectural Decision Log

Every significant decision is recorded here with its rationale.
This makes it easy to understand WHY the code is the way it is.

Format: Decision → Options considered → Choice → Reason → Trade-offs

## ADR-019: Shared Executive Situations and Proposal-Only Background Review (2026-10-20)

**Decision:** connect current evidence, supported project actions and background reasoning through
the existing cognition database, watcher and reasoner.

**Options considered:** continuously poll an unrestricted model; add another independent agent framework;
or extend existing source fingerprints, review schemas and durable execution boundaries.

**Choice:** immutable bounded situation snapshots; deterministic project preflight and result feedback;
durable, budgeted review jobs with an independent cognitive-review purpose. Keep general model tool
permissions unchanged. A separate schema forces an empty owner-facts array for background review.

**Reason:** attention needs shared evidence and observable outcomes, rather than repeated model text.
Review attempts/leases persist across restart and switches. Revalidate the whole situation and settings
epoch before committing; save the report and completion receipt together to survive the post-save crash
boundary. Internal review accounting is excluded from notification freshness checks.

**Trade-offs:** at most four background reviews/hour and 25 seconds of inference per review; short provider
attempts leave room for fallback. Unavailable providers or rejected reasoning can yield no proposal.
Live development trials saw cloud rate limits/unavailable free models and local results rejected by the
existing evidence check; no criterion was relaxed to accept them. The local project assessment/action
path works independently. This is scoped executive control, not a human brain or universal action verifier.

## ADR-018: Claimed External Checkpoints with Observation-Only Recovery (2026-10-19)

**Decision:** extend the existing execution engine for a concrete project folder workflow.

**Options considered:** execute desktop work while holding the existing SQLite transaction;
use an independent new planner; or add finite exclusive claims to existing checkpoints.

**Choice:** existing checkpoints plus token/lease claims, with source revalidation on finalization.

**Reason:** desktop operations cannot be rolled back by SQLite. Keeping the action outside the
transaction permits concurrent commands/cancellation; reconciliation observes whether an uncertain
action succeeded without authorizing another submission. Reuse the brief engine instead of building
a general planner before there are independently verifiable application adapters.

**Trade-offs:** recovery may require the owner to open the folder or explicitly start a new session.
A window observed at completion may subsequently close. Status distinguishes that historical result
from current verification. Cancel cannot undo an OS request already submitted. No claim of exactly-once
desktop effects across OS/process failures; the invariant is no blind resubmission of uncertain actions.

---

## ADR-001: Provider Abstraction Strategy

**Decision:** Use an abstract base class (ABC) for provider abstraction.

**Options considered:**
- A) Abstract base class (ABC)
- B) Duck typing (just call the same method names, no enforcement)
- C) Protocol class (structural subtyping)

**Choice:** A — Abstract base class

**Reason:**
- Forces every provider to implement the full interface
- If you forget a method, Python raises an error immediately (not silently)
- Easy to understand — the base class IS the documentation
- Compatible with standard Python tooling

**Trade-offs:**
- Slightly more verbose than duck typing
- Must import ABC — minor overhead

---

## ADR-002: Memory System (Phase 1)

**Decision:** Use SQLite for Phase 1 memory.

**Options considered:**
- A) SQLite (local file)
- B) ChromaDB (vector database)
- C) Redis (in-memory store)
- D) Plain JSON files

**Choice:** A — SQLite

**Reason:**
- Zero setup — no database server, no installation
- Single file on disk — easy to back up, inspect, delete
- Built into Python (sqlite3 in stdlib)
- More than powerful enough for Phase 1
- Easy to migrate FROM later (export to ChromaDB when needed)

**Trade-offs:**
- No semantic search (can't find "messages about Python" without keywords)
- Single-writer limitation (fine for a personal assistant)
- Will need to be upgraded in Phase 4 for semantic memory

**Future migration plan:**
Phase 4 will add ChromaDB alongside SQLite.
SQLite for structured data (facts, settings).
ChromaDB for semantic search over conversation history.

---

## ADR-003: API Framework

**Decision:** Use FastAPI for the local API.

**Options considered:**
- A) FastAPI
- B) Flask
- C) No framework (raw Python HTTP server)

**Choice:** A — FastAPI

**Reason:**
- Async by default — critical for non-blocking AI API calls
- Auto-generates Swagger UI at /docs — invaluable for testing
- Pydantic integration means request/response validation is automatic
- Modern, actively maintained, excellent documentation

**Trade-offs:**
- Requires understanding of async/await (more complex than Flask)
- Heavier dependency than Flask for simple use cases

---

## ADR-004: Config System

**Decision:** Use dotenv + a singleton Config class.

**Options considered:**
- A) dotenv + singleton class
- B) YAML config files
- C) Environment variables only (no .env file)
- D) Pydantic settings (BaseSettings)

**Choice:** A for Phase 1, with a path toward YAML for Phase 2+

**Reason:**
- Simplest option that works well
- .env files are universal — every developer knows them
- Singleton means consistent config everywhere
- Easy to add YAML support later by reading a file in __init__

**Trade-offs:**
- No schema validation (Pydantic Settings would give this)
- All config in one class can get large — will need splitting in Phase 3

**Future plan:**
Phase 2: Add `config/default.yaml` for non-secret structured config.
Phase 3: Consider Pydantic Settings for validation.

---

## ADR-005: Lazy Provider Imports

**Decision:** Import provider classes inside if-branches in registry.py, not at the top of the file.

**Options considered:**
- A) Lazy imports (inside if-branches)
- B) Top-level imports (all providers imported at module load time)

**Choice:** A — Lazy imports

**Reason:**
- The `anthropic` library is only loaded if you're using Anthropic
- The `openai` library is only loaded if you're using OpenAI
- Users don't need all SDKs installed — only the one they use
- Faster startup time

**Trade-offs:**
- Import errors are caught at runtime (when the provider is first used), not at startup
- Slightly unusual pattern — mitigated by comments in registry.py

---

## ADR-006: Event Bus (Phase 2 decision, recorded now)

**Decision:** Will use a simple in-process pub/sub event bus in Phase 2.

**Options considered:**
- A) In-process pub/sub (simple Python dict of listeners)
- B) Redis pub/sub
- C) Direct function calls (no event bus)

**Choice:** A — Simple in-process pub/sub

**Reason:**
- F.R.I.D.A.Y runs as a single process — no need for Redis
- Decouples components without adding infrastructure
- Easy to implement from scratch (50-100 lines)
- Easy to replace with Redis later if multi-process ever needed

**Trade-offs:**
- Events lost if process crashes (acceptable for a personal assistant)
- No persistence of events

---

## ADR-007: Interface Separation

**Decision:** Backend has zero knowledge of UI. All UIs are clients of the API.

**Reason:**
- Can build CLI, web UI, desktop app, voice UI without changing backend
- Backend is testable without any UI
- Clean separation of concerns

**This is non-negotiable. Do not put UI logic in backend code.**

---

## ADR-008: System Tray + Command Bar Instead of Web/Desktop UI (2026-09-14)

**Decision:** Remove the web UI and desktop UI. The system tray (pystray) plus a Win32 command bar
on Ctrl+Shift+F are the interface until a new UI is designed.

**Options considered:**
- A) Keep patching the web/desktop UIs
- B) Tray + Win32 command bar
- C) Tray + Windows toast notifications with an input box

**Choice:** B

**Reason:**
- The existing UIs were buggy, and the user wants to design a proper one later
- A tray is always present, cheap and fits an assistant that sits in the background
- A Win32 window opens instantly and can stay open while FRIDAY waits for a yes/no. Toast input is limited and unreliable.
- Both run in one process with global hotkeys (RegisterHotKey)

**Trade-offs:**
- Windows-only
- No rich rendering (markdown/code) until the new UI exists

---

## ADR-009: Local-Only API, No CORS (2026-09-14)

**Decision:** Remove CORS. Add `TrustedHostMiddleware` (127.0.0.1/localhost) and a middleware
that returns 403 to requests with a non-local `Origin`.

**Reason:**
- With the web UI gone, no browser client needs access
- Without these checks, any website open in the browser could call the API (e.g. DNS rebinding or no-CORS POSTs) and control the laptop
- Removing CORS alone doesn't block simple cross-site requests, hence the Origin check

**Trade-offs:** A future browser-based UI will need an explicit, narrow allowance.

---

## ADR-010: faster-whisper for Speech-to-Text (2026-09-14)

**Decision:** Replace `openai-whisper` with `faster-whisper` (`small`, CUDA float16, CPU int8 fallback),
preloaded at startup. Use its bundled Silero VAD to auto-stop recording.

**Options considered:** openai-whisper (existing), faster-whisper, cloud STT

**Choice:** faster-whisper

**Reason:**
- Benchmarked on this laptop: much faster, with equivalent accuracy on the test phrases
- The VAD comes free with the package, so no extra dependency for silence detection
- Stays local, so no audio leaves the machine

**Trade-offs:** Needs the CUDA build of torch for GPU speed. Currently English-only (`language="en"`).

---

## ADR-011: Streamed edge-tts with PyAV + PyAudio (2026-09-14)

**Decision:** Stream edge-tts MP3 audio and decode it with PyAV as it arrives. Play it through a PyAudio
float32 stream on one playback thread. Cache short confirmations and fall back to pyttsx3 offline.

**Reason:**
- Speech starts while the rest is still downloading, instead of after the whole file (pygame)
- A generation counter lets the voice hotkey interrupt speech mid-sentence
- Cached confirmations ("Volume set to 50%") play instantly
- Devanagari text switches to a Hindi neural voice

**Trade-offs:**
- edge-tts needs internet, so the offline voice is robotic
- Audio must be resampled to float; skipping that caused distortion

---

## ADR-012: Provider Failover and a Cheap Intent Model (2026-09-14)

**Decision:**
- Chat and voice go through `complete_with_failover()`, which tries `FALLBACK_PROVIDERS` in order when the chosen provider fails.
- The intent classifier uses a cheap model per provider, retrying on the chat model.

**Reason:**
- An outage, rate limit or stopped Ollama shouldn't make FRIDAY useless
- Classifying "is this a command?" is a tiny task, and a premium model for it wastes money and latency

**Trade-offs:**
- A fallback could use a paid provider without the user noticing. Mitigations: replies report the provider, and `FALLBACK_PROVIDERS=none` opts out.
- Cheap models return malformed JSON more often, which is why they retry on the chat model.

---

## ADR-013: Local Embeddings + SQLite for File Search (2026-09-21)

**Decision:**
- Vectors come from a small local model (bge-small-en-v1.5, sentence-transformers, GPU) and are stored as float16 blobs in SQLite, searched by brute-force dot product. Keyword search uses SQLite FTS5; file names use LIKE.
- The three rankings are merged with reciprocal rank fusion.
- "Find" never calls an AI; "answer" adds excerpts to the chat system prompt, like web search.

**Options considered:** ChromaDB; an embeddings API (only an OpenRouter key is set up); keyword search only.

**Reason:**
- Indexing ~20k chunks of the user's private files through a cloud API would send everything out; local keeps indexing private and free (about 2,000 chunks per 3.5 s on the GPU)
- At this size a numpy dot product is instant, so a vector database adds a dependency for nothing
- Keywords catch exact terms (invoice numbers, names); vectors catch meaning ("rental agreement" → lease)

**Trade-offs:**
- sentence-transformers pulls in transformers (large); the model loads in ~20 s, so it's preloaded after each scan.
- Answers still send the top excerpts to the chat provider.
- Brute-force search would need an ANN index well beyond ~500k chunks.

---

## ADR-014: Checkpointed Local Execution Before General Tool Planning (2026-10-15)

**Decision:** Begin the assistant roadmap with one managed task-handoff workflow, using an additive
`workspace_executions` table beside existing goals/tasks. Persist inputs and per-phase evidence. Publish
a deterministic Markdown artifact atomically without overwriting an existing different file; verify its
bytes and hash before success. Keep descriptive task plans separate from executable workflows.

**Options considered:** a new agent framework/background queue; general model-generated tool plans;
a short local workflow built on existing SQLite, notes and router services.

**Reason:** This produces a usable, independently verifiable path in the currently configured local mode.
Short SQLite transactions serialize concurrent phase execution; saved inputs and no-overwrite publication
make restart recovery possible without repeating unrelated actions. Existing model policy and source-task
completion semantics are preserved.

**Trade-offs:** This first workflow reads saved notes using keywords, not arbitrary project files or a
semantic planner. Explicit resume is required after interruption/failure. Long-running tools must use
separate claims/leases rather than holding SQLite transactions across network or desktop operations.
Generated handoffs are dated local artifacts retained when tracking records are cleared.


## ADR-015: Deadline JSON Authority with Explicit Reminder Links (2026-10-17)

**Decision:** Keep existing deadline readers on one canonical JSON record and require explicit links
before proposing reminder shifts.

**Options considered:** migrate all deadline consumers to SQLite; infer reminder links by text;
retain JSON authority with atomic publication and explicit reminder snapshots.

**Choice:** Retain JSON, add history/revisions/explicit links, serialize writers and use a reminder-DB
receipt to recover an approved batch after interrupted JSON finalization.

**Reason:** Existing countdown, college and briefing readers already use the deadline service. An
additive change preserves them and avoids guessing that similarly worded reminders belong together.
Approval remains separate from the owner-reported date correction and preserves existing model policy.

**Trade-offs:** Two stores require receipt reconciliation rather than a cross-file transaction. File
metadata alone is not independent proof of an owner's date claim. Canonical removal also removes local
history/links; reminder records and previously completed brief artifacts remain independent. Broader
commitment graphs and general temporal-memory reconciliation are deferred.


## ADR-016: Dated Class Overrides on the Weekly Template (2026-10-17)

**Decision:** Store a dated occurrence separately from the weekly timetable and apply its time override
through the shared effective-class projection. Preserve duration and owner-reported correction history.

**Options considered:** edit the recurring template; add timing claims to inferred semantic memory;
keep explicit dated occurrence records with guarded reminder links.

**Choice:** Atomic `class-sessions.json` records snapshot the full template and carry revisions/history.
The existing deadline writer lock serializes class/deadline reminder ownership. Reuse the established
reminder proposal/batch transaction/readback/receipt mechanism rather than introduce a second updater.

**Reason:** Existing timetable consumers can share one effective projection. Cancellation facts keep
precedence, while explicit owner corrections and separately approved reminder shifts stay auditable.
Exact template identity prevents silent rebinding after weekly edits. No relationship inference is needed.

**Trade-offs:** Separate JSON/reminder stores require receipt reconciliation. Changed/removed templates
hold linked delivery for review; already submitted notices cannot be recalled. Started/recorded classes,
cross-midnight shifts and cross-date moves are outside this workflow. General commitment reconciliation
remains deferred.


## ADR-017: Proactive Task Review Through Existing Notification Judgment (2026-10-18)

**Decision:** Select review suggestions from explicit saved tasks/goals and submit them to the existing
notification reviewer, preserving owner control over task progress and interruption preferences.

**Options considered:** expand general autonomous planning; reuse generic conversational check-ins;
connect bounded task candidates to the existing notification review/transport path.

**Choice:** Add task/goal snapshots, per-task/global preferences and single-use delivery claims in the
cognition SQLite DB. Pass exact evidence with each candidate and recheck versions/preferences before
transport. Review/pause/stop feedback never changes task progress. Existing model policy remains intact.

**Reason:** This creates useful goal-aware follow-through using verified saved state and existing
attention judgment, without assuming that an unchanged record means no real work occurred.

**Trade-offs:** Candidate scanning is bounded to 100 tasks. Same-task backoff and daily ceilings can
delay a potentially useful suggestion. OS transport cannot be atomically committed with SQLite;
unconfirmed submissions are retained without replay. Short replies are local and expire after 15
minutes; existing OS button tokens remain process-local. General autonomous work remains deferred.
