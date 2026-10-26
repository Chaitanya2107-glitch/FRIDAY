# Tkinter customization window

Current scope after the 2026-10-24 optimizer removal: a Tkinter UI for contacts,
adding/removing routines, projects and modes. Root owns all writes; two read-only reviewers
inspected service contracts, storage and tray integration. No Ruflo guidance
tool is registered. Existing unrelated work remains intact.

Build a native four-tab window with searchable record lists, labeled forms,
New/Save/Delete/Reload controls, folder browsing, unsaved-change protection and
clear validation/offline/conflict feedback. Open it from Customize FRIDAY in
the tray or `python -m interfaces.settings`. Keep HTTP work off Tk's event thread.

Use backend-owned configuration, typed local-only endpoints and shared
validation/revision protection. Serialize configuration mutations with command
edits, use atomic replacement, reject stale drafts and preserve broken files.
Editing does not send messages, execute routines, open projects or start modes.
Contact changes retire pending WhatsApp confirmations. Protect active-mode
removal.

Verify CRUD/validation/conflicts, malformed storage, retained unrelated fields,
no execution, recipient-confirmation invalidation, tray launch and real Tk forms
against temporary data. Run focused/full regression and capture a synthetic UI
preview. No real owner settings are changed during verification; no new package,
model, commit, push or deployment is required.
