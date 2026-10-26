# Checked semantic recall and explicit rescheduling

Close the remaining near-topic semantic mismatch and unsupported correction-date
field without new models, downloads, dependencies, quota increases or background
model work. Then restore useful mixed-wording recall behind the new check.

Synchronous recall stays lexical and requires full normalized content overlap.
Explicit conversation may use asynchronous checked recall: select at most one
semantic candidate, ask the existing local Ollama model once whether its specific
referent is compatible with the query. Require one grounded equivalent in the
original report for every normalized query term absent from that report, up to
six terms. Validate complete coverage, positive meaning checks and exact original
source spans, then revalidate original source availability afterward. Different or uncertain
referents, unavailable/invalid review, gaming and expired deadlines abstain. Shared
category alone is insufficient. All selection and checking share the existing
two-second recall wait budget. No retry, cloud fallback, write or action is allowed.
Background focus never invokes the semantic model check. Literal selection and
source/correction/privacy checks remain deterministic.

Restore mixed-wording candidates only through checked recall; similarity or partial
word overlap alone cannot expose them. Keep the low-level candidate selector
internal and test the final checked path in real-model evaluations.

For a verified exact correction quote with an explicit move/reschedule/postpone
`to <date>` target, recover that target only when it is unambiguous. Reject negative,
conditional, alternative or old-date-only wording. Keep the exact source target
span, anchor to its original receipt date, and leave subject/status/correction
targets to the existing validator and independent critic. Never infer a new date
from the earlier report's phrase. Do not bypass guarded persistence.

Verify known failures, fresh different-referent cases, accepted paraphrases,
source changes during checking, deadline/cancellation, disabled reasoning, gaming,
loopback-only model use, malformed output and exact spans. Separate cold startup
from warm quality probes; report missed matches and false approvals honestly.
