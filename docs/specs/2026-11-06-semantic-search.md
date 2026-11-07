# Semantic search implementation and decision receipt

User-authorized scope: implement plugins/semantic_search, offline model
preparation, explicit folder indexing, hybrid search, private Island integration,
synthetic evaluation and regression tests. No commit, push, merge or publication.

Decision: allow reversible local source changes and requested model dependency/
weight installation through sandbox approvals. Production, destructive user-file
changes and external publication remain outside scope. Index deletion is exposed
only behind an explicit expiring confirmation and affects plugin data, not sources.

One executor owns source integration. Two read-only agents inspected file reuse,
Island/routing contracts and then reviewed the implementation. No child wrote
source. Concurrent activity/clipboard edits from other sessions are preserved.
Ruflo MCP tools and a cached CLI are unavailable; repository instructions are the
coordination fallback. There is no installed tracked collaboration harness/action
capability adapter in this checkout. Graphify's existing graph was used as a map;
source reads are authoritative because the graph predates HEAD.

Acceptance: fake-embedder tests cover extraction, ranking, query filters,
incremental changes, exclusions, OCR/error handling, interrupted work, external
sources, actions, deletion, and event/log privacy. Real BGE-small inference and all
15 evaluation queries must pass without network access. Plugin/event/bridge,
legacy search, chat/voice and Island regressions must pass. No user notes are
selected or indexed as part of verification.

Architecture: independent SQLite/FTS store under plugin data_dir; interface-backed
ONNX embeddings under its model cache; per-file transactions and pending status;
one cooperative, low-priority worker; normalized float32 vectors loaded lazily;
RRF ranking; expiring opaque action/content references. Legacy private-name and
clipboard helpers are reused. Legacy extraction/model/index cannot be reused
because they lose page metadata, permit different defaults, use repo-local data
and support sending excerpts to providers.

Privacy boundary: private early dispatch precedes file/web/AI context in chat,
voice and the system router. Results are never mirrored remotely, saved to chat
history or spoken through online TTS. Event payloads carry counts/names only;
snippets use the authenticated loopback plugin route with caching disabled.

Baseline: Python 3.12.8; FastEmbed initially absent; existing legacy search and
Phase 0 plugin/event contracts inspected before writes. Candidate: FastEmbed
0.9.1 / ONNX Runtime 1.30.0 / BAAI/bge-small-en-v1.5. Verified model output is
(1,384) float32. Cached-model, throttled indexing of 20 synthetic documents
(22 chunks) took 4.969 seconds in the first successful offline evaluation;
15/15 expected files were in the top three, including three semantic paraphrases.
The one-time model fetch took approximately 25 seconds and is excluded from that
index timing. This is not a speedup comparison against the legacy index, whose
defaults and corpus behavior differ. Source hashes and final validation results
are recorded in tasks/semantic-search/validation.json after the final run.

The final source passed all 58 plugin tests. Its offline evaluation passed 15/15
queries and indexed the same corpus in 7.703 seconds with the full regression
suite running concurrently. This later number is the reported candidate timing;
the timings exclude model loading/download.

Assumptions: calendar-week interpretation; local modified-time filters; generic
notes includes docx/csv/rst; three Island rows plus Show more and a result action
submenu satisfy the six-chip contract. The 25%-of-one-core target is cooperative
throttling rather than an OS-enforced quota. OCR and unsupported file types remain
out of scope, as requested.
