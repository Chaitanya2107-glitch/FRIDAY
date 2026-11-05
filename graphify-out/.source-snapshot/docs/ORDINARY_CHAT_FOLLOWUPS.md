# Ordinary-chat date follow-ups

FRIDAY can clarify an update to an existing saved commitment in laptop chat or
voice. It uses the offered choices rather than guessing from the most recent exam.

> You: My exam was postponed.
>
> FRIDAY: Which commitment was postponed: maths exam; robotics exam?
> Reply with its name and new date.
>
> You: Robotics, November 3.

“Robotics November 3” also works in speech. You can answer just “Robotics”, then
give the date when FRIDAY asks. A question typed at the laptop can be answered
by voice. The initial statement supports “was/is/has been/got” with
“postponed/rescheduled/moved”; use the saved subject name or an unambiguous
subset of its words. Up to five matching current commitments can be offered.

Only a successful local review and committed matching revision produce
“Saved your reported date for robotics exam: 2026-11-03.” The previous date,
original owner statements, exact question and receipt dates remain in history.
Relative dates use the answer's receipt calendar, including across midnight.
This updates an interpretation of your report, not a reminder or a deadline.

Local model startup, independent critique, existing review spacing, gaming,
typing, calls and other attention limits can defer or refuse an update. FRIDAY
then says the date is not updated; it does not predict a successful save.
Say **follow-up status** or **did you save that date** to check the durable
result. A retained answer can be handled by the existing idle review, without
an additional worker or automatic notification.

Say **never mind** or **cancel** to retire an open question or an unsaved answer,
including during review. A completed save needs another explicit revision;
cancellation does not undo it. An unrelated turn retires an unanswered question.
A newer postponement retires older unsaved answers for the same offered target.
If another answer is already under review, FRIDAY asks you to cancel or repeat
the complete update rather than interpreting a second fragment independently.

Ambiguous subjects, uncertain answers, alternatives, invalid dates, receipt-day
bare weekdays and unsupported date prose do not change the saved date. Repeat
the full update after expiry or a source change. An unmatched initial report
does not retain a name-only continuation. Open questions expire in 15 minutes.

Telegram cannot inspect or answer the laptop clarification. New requested
clarifications retire earlier optional questions without training a reaction.
History clear and forgetting remove the question ledger and invalidate in-flight
reviews. Unresolved reports, intermediate names and retired answers are withheld
from recall. At most 100 clarification records are retained; existing episode
and temporal history limits still apply.

No model, provider, dependency, inference quota or action permission is changed.
The model remains fallible and the supported input patterns are bounded.
Reload backend and tray by quitting FRIDAY and running `launch_friday.vbs`.

Implementation/acceptance: [specification](specs/2026-10-22-ordinary-chat-followups.md).
Evidence and limits: [review notes](../tasks/ordinary-followups-review-notes.md).
The later [efficiency and startup measurements](../tasks/firstcall-review-notes.md)
show faster warm reviews; a first request after cold model startup can still
time out and leave the date unchanged. Check **follow-up status** for the saved result.
