# Isolated-word synonym recall

The compact whole-report checker was rejected because shared functions and
faults encouraged wrong object substitutions. Test whether checking lexical
equivalence on unmatched words, without the shared report description, improves
useful recall while retaining rejection of those substitutions.

For the existing single semantic candidate, extract normalized missing query
terms and exact unmatched non-stopword source tokens. Ask the installed local
model to map every missing term to one source word and classify the pair as a
synonym, related or unknown. Only complete synonym mappings to exact permitted
source words can pass. Source words are native schema enum values, and all
missing keys are required. Related and uncertain meanings abstain. This first
increment deliberately supports single-word equivalents only; multiword or
context-dependent equivalence may remain unresolved.

Reuse the current lexical path, semantic ranking/margin, provider, source
revalidation and channel/forget/correction guards. Keep the shared two-second
request deadline, one candidate, one local call and 192-token cap. No retries,
cloud providers, downloads, persistence or dictionary exceptions.

Implement and validate as an opt-in disposable probe first. Run known identity
failures, the previous lantern/torch and van/lorry sets, old coverage sets and a
new corpus frozen before evaluation. Unit tests establish contract and gate
behavior; actual local-model probes establish measured language behavior.
Promote only if the new evidence demonstrates coverage gains without measured
mismatch regressions. Retain all failed or unavailable trials and distinguish
deadlines from semantic refusal. A successful synthetic suite is not a guarantee
of general equivalence recognition.

Both isolated-word variants were rejected. The short classification variant
confused escalator/lift and van/lorry. Adding dictionary meanings still confused
escalator/lift and admitted two mismatches in the lantern/torch fixture set.
The prototype and original hashed revisions remain in tasks for reproducibility.
They are not wired into production. The separate recall-query-words increment
retains the conservative report check and repairs only its lossy input words.
