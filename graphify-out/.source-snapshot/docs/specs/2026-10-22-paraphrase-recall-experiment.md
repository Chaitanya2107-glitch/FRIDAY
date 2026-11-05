# Paraphrase recall experiment

Improve explicit recall of original reports when the owner uses different words.
Keep the existing two-second shared request deadline, single candidate, single
local Ollama check and 192-token generation limit. Preserve source grounding,
forgetting, corrections, channel separation and gaming/disable gates.

The hypothesis is that a compact mapping from missing query concepts to exact
source equivalents reduces output overhead and helps the installed small model
recognize synonyms. Every missing concept must have a nonempty, exact source
span; unsupported concepts map to null. A compatible referent is also required.
No synonym dictionary, extra inference, model download or threshold change.

Acceptance requires useful coverage gains while retaining mismatch abstention on
previous and fresh synthetic fixtures. Unit tests verify output contracts and
resource gates; actual installed-model probes decide semantic quality. A passing
unit suite alone cannot establish that the model understands equivalence.

Outcome: rejected for production. The candidate improved several synonym queries
but accepted a lantern as a torch. A generic related-object counterexample did
not eliminate that failure. Production was restored byte for byte. The candidate
is retained only in tasks/compact_recall_candidate.py, accessible through an
explicit --semantic --compact-candidate disposable probe. New corpora and failed
trials remain available as regressions. This does not complete the roadmap's
useful semantic recall follow-up.
