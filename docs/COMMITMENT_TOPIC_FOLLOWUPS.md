# Current commitment topics in chat and voice

Name a saved commitment once, then ask short questions about it across laptop
chat and voice:

> You: When is my robotics exam?
>
> FRIDAY: Last saved report for robotics exam: planned on 2026-10-24.
>
> You: How many days left?
>
> FRIDAY: Last saved report for robotics exam: planned on 2026-10-24
> (2 days from today).

The countdown example assumes today is October 22. It is recalculated using the
local calendar, including after midnight. The stored date remains anchored to
the original report rather than reinterpreting an old word such as "tomorrow".

Supported short questions include **when is it again**, **when is it now**,
**how many days left**, **how many days until it**, and **what was the previous
date**. **What about my maths exam?** explicitly selects a different saved
commitment. A successfully reviewed and saved date clarification also selects
its new revision, so you can immediately ask when it is or for its previous date.

The reference expires 15 minutes after selection; short reads do not extend it.
Unrelated local turns, another date clarification, **never mind**, **cancel**,
history clearing and forgetting retire it. Cancelling the topic leaves the
commitment and its history unchanged. Ambiguous names ask you to repeat a full
named question. Unoffered ordinals and the latest saved item cannot establish a
topic. Without a valid reference, FRIDAY asks for a saved commitment name.

Each answer rechecks the selected revision. A corrected, deleted, expired or
changed source needs a fresh named question. The previous date is the direct
predecessor in that commitment's correction chain; pruned or mismatched history
is unavailable. Undated, uncertain, completed, cancelled or multi-day reports
produce no countdown. A past date does not prove completion.

A slow earlier date save can finish successfully while a newer topic stays
selected. Older local requests cannot replace or clear that newer reference.

These are readbacks of the **last saved owner report**. A pending correction may
still need review; reading the old saved date does not accept that correction.
The questions make no model/search calls and change no commitments, reminders,
deadlines or tasks. They do not give **open it**, **finish it** or **remind me
then** a target or permission. Existing action workflows remain in charge.

Telegram cannot read, select or retire the laptop topic. Arbitrary topic tracking
and interpreting pronouns in unreviewed reports remain future increments; unknown
named subjects without a matching saved commitment use normal conversation.
Existing model settings, inference budgets and the remaining cold-generation
limit are unchanged.

Quit FRIDAY from the tray and run `launch_friday.vbs` again to load this feature.
See [specification](specs/2026-10-22-commitment-topic-followups.md) and
[verification notes](../tasks/topics-review-notes.md).
