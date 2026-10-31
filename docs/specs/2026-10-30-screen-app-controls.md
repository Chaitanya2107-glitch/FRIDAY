# Customizable screen app access

Owner requested allowed/blocked apps in Friday customization. Root owns all
edits; helper reviewed integration and privacy fences read-only.

Reuse catalog CRUD, conflict revisions, atomic local settings writes and the
native editor. Add Screen access with an executable-name field, app picker,
Allow reading checkbox, visible Allowed/Blocked labels, edit and delete.
Unlisted ordinary apps keep the current allowed default. An explicit Allow
does not override protected fields, sensitive content or Friday-owned windows.

Persist rules locally. Apply every save/delete without restarting: invalidate
screen generations and private conversation, preserve paused/enabled settings,
filter blocked apps out of dated conversation context, and reject late capture
or reply results. Corrupt rules fail closed and remain repairable through the
existing settings error flow. Policy reads never hold cognition DB locks.

Validate API CRUD/conflicts/local-only access, canonical process names, content
protections, corrupt storage, blocking during generation, historical filtering,
and native UI add/edit/delete and app picker. Preserve owner data and robot.
