# FRIDAY notices work on its own code

Restart FRIDAY once after installing this change. It then checks its own project
every ten seconds while running. Saving backend or Island source, adding/removing
files, or editing tests and documentation updates its development awareness.
Repeated edits to an already modified Git file are detected too.

Ask by typing or speaking:

- `development status`
- `what changed in your code`
- `are you being upgraded`

These commands work without an AI provider. They show recent change counts,
affected components and whether a restart or Island rebuild is recommended.
The command performs a fresh check; normal conversation uses the latest
background check. Command replies contain only coarse status, so filenames
cannot enter online speech services, mirrored replies or Island conversation history.

Ordinary chat and voice receive the same small factual summary through the
existing shared cognition workspace. FRIDAY can use that evidence to recognize
recent work on itself. Disabling `COGNITION_ENABLED` also disables this automatic
conversation context; the monitor, explicit status commands and API still work.

Local tools can read filenames through `GET /api/v1/mind/development`. The existing
`GET /api/v1/mind/brain` also includes coarse development state. The detailed
endpoint is restricted to local requests and uses the existing origin protection.

## What the observations mean

The first successful scan establishes a baseline. Later scans compare content
fingerprints, including additions, deletions and reversions. Returning a file to
its startup contents removes its pending restart recommendation while retaining
the history of observed edits. Documentation and tests do not recommend a
restart; backend/dependency/launcher changes do. Island sources recommend a
rebuild and relaunch.

An atomic manifest in `memory/mind/development.json` retains ten change batches,
with up to twenty paths per change kind in each batch. A new process compares
against the saved manifest to notice work between sessions, then establishes its
own startup baseline. Recent activity means a change was observed within two
minutes; it does not prove someone is still editing.

Only counts, fixed component labels, times and uncertainty enter AI context.
Source text, diffs, paths and fingerprints are excluded from those prompts.
Environment files, owner memory, logs, dependencies, build outputs, hidden files
and linked directories are excluded from monitoring. Scans are bounded by file
size, entry count and depth. A failed/incomplete scan reports uncertainty and
retains the last good snapshot; unavailable history is disclosed separately.

This observes saved files. It does not inspect unsaved editor buffers, identify
the developer, infer what a change accomplishes, verify tests, inspect an already
installed Island binary, modify its own code, or automatically restart anything.
The monitor-startup snapshot is evidence about disk contents, not proof of the
exact versions of every Python module already loaded by that process.
