# Connected cognitive inquiry and continuous attention

Owner request: stop scheduled/repetitive question batches, process answers through local reasoning,
use past/present/future context, and connect features to shared cognition while FRIDAY runs.

## Behavior and implementation order

1. Store provenance-bearing owner dialogue episodes (including the original question and short answer)
   in the existing cognition SQLite database. Feed them to reasoning, notification decisions and relevant
   conversation recall. Preserve original dates and distinguish owner reports from verified observations.
2. Generate at most one question per local brain decision. Supply recent episodes, goals/tasks, current
   activity, dated facts, upcoming effective classes/deadlines/reminders, reactions and prior questions.
   Validate a typed decision with actual evidence IDs and a rationale; silence is normal. No fixed quota,
   mandatory launch interview, time-of-day question queue, or automatic next question after six seconds.
3. Centralize question timing/duplicate checks, durable claims and attempt budgets. Respect busy/gaming,
   typing, absence, microphone/speech, pending confirmations/questions, upcoming commitments, pause/off,
   ignored answers and rejections. Recheck sources and preferences after model latency and before delivery.
   Limit automatic interruptions to at most three per day, at least 45 minutes apart; never a target.
4. Route explicit ask/day-review/learning requests through the same brain, one question per request.
   They are requested replies, not permission to start an unattended series. Unavailable local reasoning
   produces no autonomous question or fallback script. Ordinary remote commands cannot answer a local question.
5. Connect request/action/outcome/notification and feature-write events to a lightweight attention wakeup.
   Reuse durable executive review and its budgets. Timers reconcile missed work; they do not mandate speech.
   Keep immediate explicit execution checks local and deterministic; generated reasoning does not grant
   tool permissions or bypass confirmations. No model inference for every UI poll or keystroke.
6. Expose local brain/question status and decision reasons, integrate memory forgetting/in-flight fencing,
   and document exactly which boundaries are connected and what remains outside general autonomous planning.

## Verification

Reproduce repeated queue delivery and unprocessed answers. Test no scheduled batches, silence, varied
generated questions, source citations, local-only inference, timing inhibition, answer provenance and recall,
changed sources/preferences during inference, restarts/concurrent claims, duplicate topics, model failure,
channel isolation, forgetting, event wakeups, command/action connections and full application regressions.
Use synthetic context for live model probes; never send notifications, execute commands or modify owner data.

This is functional software cognition, not a claim of human consciousness. The loop works while the
application/laptop run and defers expensive local inference during gaming. Model outages do not disable
explicit local commands, existing action confirmations or recoverable reminder delivery.
