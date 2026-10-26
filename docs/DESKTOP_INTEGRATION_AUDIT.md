# FRIDAY desktop integration audit — 2026-10-24

Final verification is in progress. Exact source and results will be recorded in
`tasks/desktop-integration-verification.json`.

## Coordination and source ownership

The separate taskbar chat is outside this session's messaging registry. A shared
request was left at `tasks/taskbar-integration-request.md`; the saved taskbar
validation and installation receipts supplied the handoff. All 24 recorded
source hashes matched before integration. Its receipt recorded 218 regression
checks and four native GUI checks; installation completed at 13:48:38 UTC.
The integration session used two read-only reviewers and preserved that baseline
in a ZIP. A later layered-window fix and on-screen assertions arrived from the
other session during the first full run. That run is retained as preliminary;
the changes are reconciled in the final source snapshot before a fresh run.

## Problems found and corrected

| Finding | Resulting behavior |
| --- | --- |
| The VBS launched a resident widget and intentionally waited for a click before starting the backend. This conflicted with the owner's later background-startup request. | Normal launch now starts FRIDAY once through the existing lifecycle worker. VBS, BAT and shortcuts use that common path. |
| A repeat launch showed the flyout but left a stopped backend stopped. | Launcher activation shows the existing flyout and requests startup when offline. Online, busy and already-owned states avoid duplicate starts. |
| Any HTTP 200 from `/health` was treated as FRIDAY. | The shared health check requires FRIDAY's service identity, rejects malformed replies and bypasses environment proxies for this local check. |
| The gaming editor hid inherited global app limits. Empty profile overrides could therefore appear unrestricted. | Shared limits now appear in a read-only scrollable sidebar. Keep normal explains its override behavior; inherited apps do not become saved profile overrides. |
| The Customize menu connection had only been tested in separate pieces. | A native integration check now invokes the rendered All controls menu entry and verifies the customization launcher callback, including offline availability. |
| A native child could exist and accept off-screen painting without appearing above the taskbar's composited surface. | The taskbar session's final layered-window fix is preserved, with actual on-screen pixel assertions in the final native tests. |

The taskbar session's cursor-access guard, separate launcher show callback,
anchored flyout, Stop/Exit distinction and parent-recovery behavior were
preserved. Its cursor fix handles Windows temporarily denying cursor access;
the old desktop log records the original repeated failure. No extra callback or
second taskbar/menu implementation was introduced.

## Expected operation

Run `launch_friday.vbs`. FRIDAY starts in the background and the resident button
remains available. **All controls → Customize FRIDAY…** opens the five native
editors: contacts, routines, gaming profiles, projects and modes.

**Stop FRIDAY** leaves the widget resident. Idle refresh does not restart the
backend; a launch, button click or Start request does. **Exit taskbar widget**
closes that desktop and its owned backend. A manually started backend keeps its
separate ownership, and user applications are preserved.

Forms keep validation, draft protection, background HTTP, revision conflicts,
atomic storage and confirmation fencing. Saving a form never executes stored
commands, sends a message, opens a project or activates a mode.

## Verification

- Focused startup/native integration run: **51 passed**, including the actual
  Customize menu callback, duplicate activation states and Stop persistence.
- Complete regression suite: pending final result in
  `tasks/desktop-integration-final-full.xml`; native GUI checks are enabled and
  unraisable/thread exception warnings are treated as errors. The preliminary
  run passed 5,700 tests but included a Tk test-window cleanup warning and late
  source edits. Direct-build test cleanup now releases Tk resources on its
  owning thread, matching the production cleanup path.
- All **444 Python inputs** parse. New and changed scoped files are under 500
  lines, with no trailing whitespace.
- `pip check`: no broken requirements found.
- Read-only SQLite quick checks: `friday.db` and `learning.db` both returned
  `ok`. These checks establish physical integrity, not correctness of facts.
- All five live customization catalog endpoints returned HTTP 200 during
  preflight, with revision information. No owner records were created or edited.
- Five synthetic native previews were captured under
  `tasks/desktop-integration-preview/`; the gaming view was inspected after
  moving shared limits to the sidebar so both checkboxes remain visible.
- Final real VBS startup, duplicate-process, live frontend and editor-window
  check: pending in `tasks/desktop-integration-live.json`.

The final source snapshot is `tasks/desktop-integration-final-source.zip` with its
SHA-256 manifest. Final evidence will distinguish executable test inputs from
auxiliary probe-script changes and any source movement after a run.

## Items requiring attention

| Item | Evidence and practical limit |
| --- | --- |
| Current capability mode | Workspace configuration resolves `AI_ASSIST_ONLY=True`. Text conversation remains enabled through the language path, while screen/computer tasks and ad hoc reasoning are gated by this mode. Cognitive review has its own allowed path. General regression fixtures explicitly set assist-only false; passing cases do not establish availability of gated features under the owner's current mode. This integration preserves the preference. |
| Cold local-model inference reliability | The prior installed-model checks still document a first-generation timeout. This integration makes no model/runtime changes and does not re-test live generation. See `BRAIN_LIFE_ROADMAP.md` and `tasks/firstcall-review-notes.md`. |
| Embedded taskbar compatibility | Explorer does not reserve the widget's gap. The current implementation measures the primary horizontal taskbar and hides the button if it cannot find safe space. The hotkey and Start menu remain fallbacks. Parent replacement is tested with disposable windows; this run does not restart Explorer. |
| External feature validation | Live message sends, cloud-provider replies, microphone recordings and real gaming-priority changes are not exercised here. Their isolated regressions do not establish every external service or hardware state. |
| Test artifact permissions | Earlier unscoped discovery encountered retained ACL-restricted temporary directories under `tasks/`. The complete production suite is explicitly run from `tests/`; unrelated artifacts are preserved. |
| Existing test-client deprecation | The installed Starlette/httpx test-client warning predates this change. Dependency integrity passes; no package versions were changed. |

No commits, pushes, releases, dependency changes or model changes were made.
