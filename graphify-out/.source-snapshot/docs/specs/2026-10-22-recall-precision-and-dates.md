# Conservative recall and date resolution

Continue the brain cross-check findings without new models, downloads, dependencies,
provider changes, inference quotas, persistent indexes or background model work.

## Recall

Partial word overlap is insufficient support for a query that contains other
content words. Require all normalized query content terms for lexical selection.
Apply the same veto to the best embedding candidate when it matches some query
terms but leaves others unsupported. Similarity alone cannot override that veto;
do not fall through to a weaker source. Purely reworded candidates with zero exact
content overlap may still pass the existing similarity/margin checks.

This is conservative abstention, not an entity recognizer or proof of identity.
It intentionally loses some valid mixed literal/paraphrased queries. Existing
simple token inflection limits also become more visible (e.g. `map` / `maps`).
Zero-overlap near-topic candidates can still confuse different objects; record
these failures instead of adding domain-specific exceptions or tuning thresholds
against the evaluation. Original source, correction, privacy, current-turn,
forgetting, deadline and serialized-context limits remain authoritative.

## Dates

If a model date phrase is missing or does not occur in the original text/question,
an initial planned/uncertain report may reuse the existing deterministic recovery
of exactly one unambiguous calendar span from its verified exact source quote.
Discard model-supplied bounds and anchor the recovered span to original receipt
time. Do not recover dates from negated/ambiguous/old-date correction wording, or
repair correction targets/status/subject relationships. Native validation and the
independent critic still gate persistence. Unsupported recovery remains rejection.

Calendar expressions may include the leading prepositions `to`, `on` or `for`;
retain the exact original date phrase while normalizing it for calendar arithmetic.
Do not turn `from`, `after`, `next` or alternatives into an invented exact day.

A reviewed postponement with known bounds belongs in the shared current/upcoming/
past group according to its new date. Both temporal and behavioral consumers must
agree. An undated postponement remains unresolved, as does an uncertain report.

## Verification

- Regression tests reproduce high-similarity wrong-object retrieval and malformed
  model timestamps before fixes; preserve positive exact and pure paraphrase paths.
- Date tests cover source-grounding, ambiguity, negation, corrections, prepositions
  and agreement between the temporal and behavioral shared views.
- Freeze a new recall corpus before implementation. Keep the audit and older sets
  as regressions. Report both positive coverage and negative abstention, including
  losses caused by the stricter rule. Do not claim universal identity discrimination.
- Use synthetic local-model trials for initial interpretations and revisions. Keep
  failed trials. Separate a regression replay after a discovered bug from genuinely
  fresh evidence and retain production/corpus hashes.
