# Telegram upgrades

Owner request: add one-command confirmation bypass, readable briefings, offline
command catch-up, direct keyboard shortcuts, and replies to local diagnostics.

## Acceptance criteria

- `/! <command>` skips FRIDAY's confirmation prompts for that message, including
  typing, file uploads and power actions. It never enables a persistent mode.
- `/cc right-arrow`, `/cc enter` and valid key combinations press the requested
  keys in the focused laptop window. Invalid keys never reach Windows.
- Messages sent while FRIDAY is offline run in order after reconnection or
  restart. Telegram retains unseen updates for at most 24 hours. A durable local
  inbox records received updates before acknowledging them to Telegram.
- Interrupted executions with an unknown outcome are reported, not replayed
  automatically; completed commands are not repeated after restart.
- Daily, nightly, weekly and learning reports use emoji section headings and
  bullets. Spoken briefings retain their existing prose. Long replies retain
  their complete text across Telegram message boundaries.
- The authenticated bot owner in their private chat can read local brain, executive, notification,
  reasoning and recorded-event diagnostics. Remote clipboard/login prohibitions,
  forwarded-command rejection, lockdown and laptop/Telegram isolation remain.
- Offline `yes` replies cannot confirm a question first issued after reconnect.
  The `/!` prefix is also limited to the owner's private chat.

## Implementation and validation

The integration agent is the sole writer; two read-only researchers reviewed
command execution and report formatting. Existing unrelated working changes
are retained. No publication or repository commits are authorized by this task.

Ruflo's cached CLI is available; AgentDB memory search reported no database.
Its routing/swarm adapters failed the sandbox's Windows user lookup. The
escalated policy check reports legacy mode with no enforced rules or capabilities.
The development edit decision is allowed, receipt
`sha256:6dc9f5100a19ac1132c72d644d31a82472a83cca9a942ab8c2350cdc82a9cd05`.
This receipt records the decision; it does not grant additional authority.

Baseline: 166 focused tests passed before editing. Evidence:
`tasks/telegram-upgrades-baseline.xml`.

Final regression: **1,069 passed**, no failures/errors/skips, including a
same-poll queued-confirmation regression. Evidence:
`tasks/telegram-upgrades-receipt-tests.xml`. Source hashes and activation state:
`tasks/telegram-upgrades-verification.json`; the source manifest covers 451
Python/source inputs, including existing working changes.
Activation completed through the normal desktop close/launch lifecycle. The
managed backend passed health readiness, Telegram is configured and its new
startup marker was verified. Activation policy and process IDs are in the receipt.

Validation covers real bot-to-chat routing with fake external I/O, one-message
scope and exception cleanup, ordinary confirmations, owner checks, offline
ordering/restarts/duplicates, formatting and the existing Telegram regressions.

Telegram semantics: https://core.telegram.org/bots/api#getting-updates and
https://core.telegram.org/bots/api#getupdates.
