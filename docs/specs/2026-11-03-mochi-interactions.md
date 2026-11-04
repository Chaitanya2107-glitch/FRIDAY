# Default capsule and passive Mochi

The owner requested the clock/date/battery capsule as the default instead of the
Mochi-only island, and removal of Mochi's click animations. This supersedes the
earlier small-island and reaction-card request.

Resting and passive hover modes show the existing 288 x 32 black capsule, with
amber Mochi, clock, date, and battery. The optional media strip remains available.
Mochi stays centered when idle and moves to the left for replies and reminders.
Clicking the clock/background opens the existing 640px command editor. Expanded
FRIDAY, project, plugin, and settings controls retain their existing behavior.

Mochi is a passive SVG image. Clicking it produces no reaction, animation, card,
mode change, or loss of command focus. The reaction implementation, timers,
expressions, popup, CSS keyframes, and related native regions are removed.
Original idle animation and pointer-following eyes remain.

Reply layouts, pending and private replies, drafts, media controls, and motion
preferences remain intact. Validate focused browser behavior, existing bridge
and authenticated reply fixtures, TypeScript and unit checks, and the staged
native executable before activating through the normal local launcher.

Reminders use the same message view as FRIDAY replies. The compact reminder
label beside the clock is removed. Dismissal restores the centered idle capsule;
clicking message text keeps it visible. Near-class reminders still respect their
setting. Queued reminders wait behind pending replies and active drafts.

The root agent owns writes; the review helper is read-only. Preserve unrelated
workspace changes. No commit or publication is authorized.
