# Capsule replies

Owner request: move Mochi to the left side of the capsule when replying to a
command or presenting a reminder. Use the capsule for the reply rather than
automatically opening the expanded conversation panel.

## Acceptance

- Typed and nonprivate voice replies use the same capsule presentation.
- Brief replies expire after five seconds; long or multiline replies, reminders,
  errors and work results expire after 30 seconds. Reading pauses expiration.
- The acknowledge button removes the current display. Pending confirmations
  remain until answered or dismissed; dismissal never approves an action.
- Reminder actions keep their existing validated tokenized runtime path. A late
  action result cannot dismiss an unrelated reminder.
- Public history remains in the FRIDAY tab. Private replies clear on dismissal,
  mode changes, blur and disconnect, and never enter public history.
- Focused drafts/editors keep their focus. Queued reminders start their display
  timer when shown; acknowledgement advances to the next reminder.
- Mochi slides from the center to the left edge, respecting reduced motion.
  Long text is scrollable, selectable and bounded within the native hit region.
- Sneak mode continues to suppress the Island and use its command bar.

## Implementation and checks

Reuse Rest mode and native geometry; add a bounded live reply queue and CSS
presentation. Route existing response, question and reminder events to it, forward
short nonprivate voice replies as transient events, and watch automation state
changes for work completion without replaying old snapshots on connection.

Validate retention classification, authenticated transient event routing, real
Chromium command/reminder/work flows, acknowledgement/timing/queue races, private
cleanup, draft preservation, Sneak mode, and native Windows bounds/focus/clicks.
Exact source/build inputs and results: `tasks/island-replies/receipt.json`.
