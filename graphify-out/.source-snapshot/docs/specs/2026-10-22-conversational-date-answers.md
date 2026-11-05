# Conversational answers to retained date questions

Extend the existing whole-date reply path to affirmative wrappers such as
"It's on October 27", "It will be on November 3", "That's for November 3",
"It is scheduled for October 27" and "The date is October 27". Support straight
and curly apostrophes, case and whitespace without rewriting the stored answer.

Remove only a fully anchored, explicitly supported present/future prefix. The
remaining entire suffix must be one date expression supported by the current
calendar resolver. Preserve that suffix as an exact contiguous original span
and preserve the complete original answer as the model quote. Keep the raw
120-character bound before any stripping. Questions, uncertainty, negation,
alternatives, multi-day ranges, trailing qualifiers and unsupported prose cannot pass by
merely containing a date. Same-receipt bare weekdays remain unresolved.

Use the existing offered local inquiry ID, current gap/version/epoch and single
undated target. Do not infer scope from pronouns or similar question text. Keep
receipt-time anchoring, pending-correction prioritization, native schema, model
generation, independent critique and transactional source/inquiry validation.
Unlinked wrapped answers must also be blocked from bypass through ordinary
review, including targets named after calendar months.

This increment does not extract dates from arbitrary conversation, attach dates
to ordinary chat without retained inquiry provenance, change any reminder or
deadline, generate extra questions, introduce another model call or alter any
provider, inference/attention budget or dependency. Prioritize minimal changes
to answer_date_phrase and verify whole intake/review/persistence against frozen
synthetic fixtures, plus rejection, forgetting and stale-proof regressions.
