# GitHub integrations for FRIDAY

Researched 2026-10-22 against official repositories, release metadata, source
manifests and maintainer documentation. Research only: no packages installed,
models downloaded, repositories cloned or runtime integrations tested.
Ranks reflect proposed FRIDAY value, not popularity. Effort estimates are judgments.

Later owner-approved work on the same date integrated Playwright/pywinauto and
Scrapling (an additional candidate discussed after this shortlist). See
[browser/research implementation and checks](../BROWSER_AUTOMATION.md).
The research-only statement above describes this original comparison; the other
shortlisted candidates remain proposals.

## Recommendation

Start with Trafilatura for useful web reading. Run a small Wn recall experiment
alongside it before changing memory behavior. Add Playwright when there is a
specific browser workflow to support. Do not add all ten dependencies together.

FRIDAY already has local Ollama reasoning, BGE embeddings, SQLite, Parakeet and
Whisper speech recognition, Piper speech synthesis, DDGS discovery, ordinary
PDF/Office extraction, native action guards and a substantial pytest/probe suite.
The proposals below extend those components rather than replace the assistant.

## Ten candidates

### 1. adbar/trafilatura - readable web evidence

[Repository](https://github.com/adbar/trafilatura) |
[Python API](https://trafilatura.readthedocs.io/en/latest/usage-python.html) |
[installation](https://trafilatura.readthedocs.io/en/latest/installation.html)

Extract article text and metadata from HTML discovered through existing DDGS
search. Proposed seam: `services/search/web_search.py`; pass already fetched HTML
to extraction, retain URL/title/date and fall back to snippets when it fails.
Keep bounded fetching/output and treat page instructions as untrusted content.
This does not render JavaScript or establish that an article is true.

Apache-2.0 for current versions; older pre-1.8 versions used GPLv3+.
Python >=3.10, explicitly includes 3.12, with Windows testing documented.
Ordinary extraction needs no inference model. Start without optional extras.
Effort: small/medium. Verify useful content and provenance on a fixed mixed-site
corpus, including empty extraction, large pages and fetch failures.

### 2. goodmami/wn - precise vocabulary support for recall

[Repository](https://github.com/goodmami/wn) |
[Python manifest](https://github.com/goodmami/wn/blob/main/pyproject.toml) |
[lexicon index/licenses](https://github.com/goodmami/wn/blob/main/wn/index.toml)

Provides WordNet lookup, morphological normalization and lexical relationships.
Proposed seam: `services/mind/recall.py`, as bounded candidate generation and
lexical evidence before existing source-bound checking. It may improve spelling,
inflection and genuine synonym coverage without another language-model call.
Related words are not interchangeable objects; do not expand every hypernym or
declare that a synonym match proves a remembered fact.

MIT code; a separately obtained lexicon is required. Open English WordNet is
CC BY 4.0: pin its version, retain attribution and distinguish its terms from
the library license. Python >=3.10, explicitly includes 3.12. Offline lookup
after provisioning; disk/startup cost needs measurement. Effort: medium.
Proceed only if the existing positive/negative recall probes improve while
abstentions, source checks and the two-second shared deadline remain intact.

### 3. microsoft/playwright-python - reliable browser workflows

[Repository](https://github.com/microsoft/playwright-python) |
[requirements](https://playwright.dev/python/docs/intro#system-requirements) |
[actionability](https://playwright.dev/python/docs/actionability) |
[browser installation](https://playwright.dev/python/docs/browsers)

Locators, browser state and automatic actionability waits could improve
explicitly requested website workflows beyond coordinate-only input.
Proposed seam: the existing computer-action layer, through named bounded tools.
Retain confirmation for consequential submissions and verify business outcomes;
a successful click alone is not a completed task.

Apache-2.0. Python >=3.10 includes 3.12; official Windows requirements currently
specify Windows 11+ or Server 2019+. Versioned browser binaries add download/disk
cost and browser processes consume RAM. An installed supported Edge/Chrome
channel may be an option. Effort: medium/high. Start one worker on demand with
one concrete workflow; test stale pages, redirects, login boundaries and failure
receipts before enabling broader use.

### 4. rapidfuzz/RapidFuzz - helpful name/typo suggestions

[Repository](https://github.com/rapidfuzz/RapidFuzz) |
[installation](https://rapidfuzz.github.io/RapidFuzz/Installation.html) |
[matching API](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html)

Rank close app, file or command names when exact resolution fails. Proposed
seams: app/file search and the suggestion boundary around
`services/automation/command_typos.py`. Return a suggestion, not execution
permission. Preserve explicit parsing and never fuzzy-rewrite recipients,
paths or command arguments into an action.

MIT, local CPU operation, Windows wheels; Windows native runtime requirements
include the Visual C++ redistributable. No model download. Effort: small if a
measured search gap exists; retain the current whitelist where it already works.
Test collisions, short names, near-identical apps and rejection thresholds.

### 5. pywinauto/pywinauto - Windows controls and readback

[Repository](https://github.com/pywinauto/pywinauto) |
[Python support](https://github.com/pywinauto/pywinauto/blob/master/setup.py) |
[desktop limitations](https://pywinauto.readthedocs.io/en/latest/remote_execution.html)

Win32/UI Automation can address controls by properties and read their state,
improving targeting and verification for supported Windows apps. Add an adapter
within `services/computer/`; retain native allowlists, confirmations, focus and
gaming deferrals. Not every custom UI exposes useful accessibility controls.

BSD-3-Clause; Python 3.12 is declared. No model required, but interactive input
depends on an available desktop and can fail when locked. Current 1.0.0b1 is a
prerelease with major changes, while published docs still describe 0.6.8.
Effort: medium. Pin a deliberately selected version and test actual target
apps, elevation mismatches, stale handles and post-action state.

### 6. docling-project/docling - scanned PDFs and structured tables

[Repository](https://github.com/docling-project/docling) |
[manifest](https://github.com/docling-project/docling/blob/main/pyproject.toml) |
[offline/model options](https://docling-project.github.io/docling/usage/advanced_options/)

Use as an optional fallback for scanned or layout-heavy documents where current
`services/files/extract.py` text extraction is inadequate. Retain page/table
provenance, private-file exclusions and file/page/output limits. Keep existing
lightweight parsers for ordinary files; run costly conversion in a bounded worker.

MIT code; downloaded models have separate terms. Official
[Heron model card](https://huggingface.co/docling-project/docling-layout-heron/blob/main/README.md)
declares Apache-2.0; the
[model bundle card](https://huggingface.co/docling-project/docling-models/blob/main/README.md)
lists CDLA-Permissive-2.0 and Apache-2.0. Review chosen OCR/model assets separately.
Windows/Python 3.12 declared. Models may download on first use unless explicitly
provisioned; full OCR/PDF disk/RAM cost is not measured here. Current packaging
uses modular docling-slim/extras. Effort: high. Benchmark scanned pages, tables,
page citations, timeouts and resource use before opting in.

### 7. scrapinghub/dateparser - broader date-language coverage

[Repository](https://github.com/scrapinghub/dateparser) |
[settings](https://dateparser.readthedocs.io/en/latest/settings.html) |
[release history](https://github.com/scrapinghub/dateparser/blob/master/HISTORY.rst)

Possible optional parser behind `services/mind/temporal_memory.py` when broader
language/date coverage is requested. Set relative base to the original receipt,
explicit timezone and deliberate date order; defaults are not sufficient.
Consider strict parsing and restricted parser/language choices. A successful
parse cannot resolve which exam the owner meant or prove an intended correction.

BSD-3-Clause; no inference model. Effort: medium/high because permissive parsing
can weaken existing rejection behavior. Keep whole-answer, ambiguity, negation,
inquiry provenance, independent critique and atomic persistence checks.
Replay the existing date controls plus locale/relative-date cases. Current
1.4.3 includes concurrency/settings fixes relevant to service use.

### 8. k2-fsa/sherpa-onnx - dedicated FRIDAY keyword spotting

[Repository](https://github.com/k2-fsa/sherpa-onnx) |
[keyword spotting](https://k2-fsa.github.io/sherpa/onnx/kws/index.html) |
[custom keywords/models](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html) |
[Windows CP312 artifacts](https://k2-fsa.github.io/sherpa/onnx/cpu.html)

Open-vocabulary keyword spotting supports custom keywords without retraining a
classifier. Could avoid full STT for every possible wake utterance. Feed one
CPU spotter from FRIDAY's existing audio owner and emit its existing wake event;
retain Parakeet/Whisper for actual requests and current opt-in/mute/cancel rules.
Use the selected model's tokenizer for HEY FRIDAY.

Apache-2.0 code; verify licenses for the exact weights, tokens and dictionary
before bundling. A model author reported an Apache license update, but
[asset-license issue #3802](https://github.com/k2-fsa/sherpa-onnx/issues/3802)
remains open. This is a conditional prototype, not blanket asset clearance.
Windows CP312 wheels exist. English KWS release packages observed around
15-17 MiB compressed, not installed RAM/size estimates.
[Model release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/kws-models).
Effort: medium/high. Measure missed wakes, false accepts during music/TTS,
accents, cancellation and sustained CPU during gaming before default use.

### 9. promptfoo/promptfoo - optional evaluation tooling

[Repository](https://github.com/promptfoo/promptfoo) |
[installation](https://www.promptfoo.dev/docs/installation/) |
[Python providers](https://www.promptfoo.dev/docs/providers/python/) |
[grading defaults](https://www.promptfoo.dev/docs/configuration/expected-outputs/model-graded/#overriding-the-llm-grader)

Useful for repeatable prompt/model comparison reports around FRIDAY's existing
probes, not a replacement for pytest. Keep it in developer/CI tooling, with a
thin Python provider calling the existing bounded local inference client.
Reuse current corpora and deterministic assertions rather than duplicate tests.

MIT; Node >=22.22.0 is required despite Python adapters. No target model is
included. Model-graded assertions may choose providers from available credentials:
local target inference alone does not guarantee local grading. Use deterministic
checks first; explicitly configure every grading/embedding provider if added.
Effort: medium. Preserve concurrency, token, deadline and call-budget accounting.
Only adopt if reports materially improve the existing evaluation workflow.

### 10. asg017/sqlite-vec - optional vector-search scaling

[Repository](https://github.com/asg017/sqlite-vec) |
[Python integration](https://alexgarcia.xyz/sqlite-vec/python.html) |
[installation](https://alexgarcia.xyz/sqlite-vec/installation.html)

Native SQLite vector search could serve larger local file/memory collections
without a separate vector database. Reuse current BGE embeddings; this is a
search engine, not an embedding model or an answer-quality fix.
Proposed seam: file indexing first, and memory only after lifecycle proof.

MIT/Apache-2.0 licensing; C extension with Windows support, but explicitly pre-v1
with possible breaking changes. Effort: medium/high. First demonstrate current
retrieval is a bottleneck and test extension loading in this exact Python build.
Persisted vectors need source IDs, embedding version, rebuild/migration rules,
and atomic deletion/forgetting. Do not replace intentionally ephemeral memory
embeddings without proving stale evidence cannot survive corrections or forgetting.

## Maintenance snapshot

All ten repositories were observed as not archived. Push date is repository
activity, not necessarily a default-branch code change or proof of quality.
GitHub metadata endpoints: `https://api.github.com/repos/{owner}/{repo}`;
release links below identify the observed release rather than promising a pin.

| Repository | Observed release | Published | Activity observation |
| --- | --- | --- | --- |
| adbar/trafilatura | [v2.3.1](https://github.com/adbar/trafilatura/releases/tag/v2.3.1) | 2026-10-06 | pushed 2026-10-21 |
| goodmami/wn | [v1.1.1](https://github.com/goodmami/wn/releases/tag/v1.1.1) | 2026-08-14 | pushed 2026-09-05 |
| microsoft/playwright-python | [v1.64.0](https://github.com/microsoft/playwright-python/releases/tag/v1.64.0) | 2026-10-13 | default-branch commit 2026-10-21 |
| rapidfuzz/RapidFuzz | [v3.14.6-1](https://github.com/rapidfuzz/RapidFuzz/releases/tag/v3.14.6-1) | 2026-08-30 | pushed 2026-10-21 |
| pywinauto/pywinauto | [1.0.0b1, prerelease](https://github.com/pywinauto/pywinauto/releases/tag/1.0.0b1) | 2026-10-15 | default-branch commit 2026-10-21 |
| docling-project/docling | [v2.141.0](https://github.com/docling-project/docling/releases/tag/v2.141.0) | 2026-10-20 | pushed 2026-10-22 |
| scrapinghub/dateparser | [v1.4.3](https://github.com/scrapinghub/dateparser/releases/tag/v1.4.3) | 2026-09-03 | pushed 2026-10-21 |
| k2-fsa/sherpa-onnx | [v1.13.8](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.13.8) | 2026-09-10 | pushed 2026-10-22 |
| promptfoo/promptfoo | [application 0.124.1](https://github.com/promptfoo/promptfoo/releases/tag/0.124.1) | 2026-10-08 | pushed 2026-10-22 |
| asg017/sqlite-vec | [v0.1.9](https://github.com/asg017/sqlite-vec/releases/tag/v0.1.9) | 2026-03-31 | pushed 2026-05-18 |

Promptfoo's latest-release endpoint currently selects a separate code-scan action;
that is not the application version. Release metadata is an observation, not a
dependency lockfile. Exact runtime compatibility remains untested for all ten.

## Screened alternative and deferred feature

openWakeWord was considered but not selected: its code is Apache-2.0, bundled
pretrained models are CC BY-NC-SA 4.0, built-ins lack FRIDAY, custom classifiers
require training, and latest listed release v0.6.0 dates to February 2024.
[Project/model terms](https://github.com/dscripka/openWakeWord#license) |
[custom training](https://github.com/dscripka/openWakeWord#training-new-models).
Sherpa offers a more direct custom-keyword experiment, subject to asset review.

Reliable ordinary-chat follow-up conversations remain queued in
[BRAIN_LIFE_ROADMAP.md](../BRAIN_LIFE_ROADMAP.md), explicitly deferred by the owner
while this research is evaluated. None of these libraries alone supplies correct
topic linkage, clarification, commitment revision or permission semantics.

This document changes no application behavior. No application tests were run
for this documentation-only research update.
