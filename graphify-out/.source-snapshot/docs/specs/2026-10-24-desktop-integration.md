# FRIDAY desktop integration verification

Owner request: reconcile the new taskbar widget with Tkinter customization,
repair missing VBS/background startup, test after the taskbar handoff, and report
what is broken or still requires attention. Preserve all unrelated work.

Baseline is the source-bound taskbar receipt checked at 13:47:56Z on October 24,
with all 24 hashes matched before integration. Source and installation receipts
provide the handoff because the separate chat is outside this agent registry.
Root owns integration writes; two helper audits are read-only.

Normal desktop startup must request backend startup once through the existing
worker. Duplicate activation shows the flyout and starts a stopped backend.
Stop leaves the widget resident; idle refresh does not restart the backend.
Manual backends and applications started by FRIDAY retain their ownership.

Backend health must identify FRIDAY, rather than accept an unrelated HTTP 200.
The actual native All controls menu must invoke the customization launcher.
All five forms and local CRUD routes retain validation and draft protection.
Gaming profiles must explain inherited global limits and Keep normal overrides.

Validate with focused regressions, opt-in native GUI checks, the complete tests/
suite, syntax/dependency checks, and a real VBS/background health probe. Bind
results to exact source hashes and disclose any concurrent source changes.
Use temporary settings and stand-ins for message, microphone and command effects.
Live checks read saved catalogs; do not create contacts, run routines or send
messages. Leave the successfully launched assistant running for the owner.

No dependencies, model changes, commits, pushes or publication are authorized.
GUI and other restricted execution use the environment permission mechanism.
