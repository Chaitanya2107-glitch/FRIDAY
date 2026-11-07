# Mochi moods

Authorized scope: local plugin, event producers, Island SVG reactions, tests and
measurement. No commit, push, release, user-data migration or real notification.
Root is the only writer; event-producer and native-comfort agents are read-only.
Existing uncommitted changes are retained. Ruflo's offline CLI is unavailable
(package not installed); coordination and decisions are recorded here instead.

Acceptance: eleven moods; ordered priority arbitration with sticky return;
validated live JSON rules and cooldowns; calm/quiet filtering; ten-minute idle
and active late-night rules; authenticated SSE; focus start/pause/resume/finish;
subtle amber SVG poses, four-second 60-character peek bubbles; motion preferences,
hidden/fullscreen suspension, 30 fps maximum; focused automated tests and native
process-tree CPU evidence. Existing dimensions, hotkeys and click behavior stay.

Implementation decisions:

- `plugins/mood` owns the sole runtime arbiter. The old controller is a small
  compatibility adapter to that same implementation.
- One ordered wildcard subscription avoids cross-subscriber races. A managed
  one-second tick handles expiry, idle thresholds, focus and atomic rules reload.
- Focus/study/exam priority is 4; game/sleep/dozing priority is 1 or 2. Quiet
  scenes suppress reactions below 4, including the quiet scene's own low mood.
- Sticky contexts retain their owners and latest order, so ending one scene
  cannot clear another scene/focus. Interrupted temporary moods are discarded.
- Late night means local 01:00–05:59, with recent input, once per 30 minutes;
  this avoids sleepy reminders throughout the afternoon. No audio is added.
- Focus events come from the existing `focus` plugin (added by adjacent work
  during implementation). The mood plugin registers no competing focus timer.
  Mood contexts survive rules edits; plugin code reload resets mood contexts.
- Rules JSON is excluded from host code fingerprinting for this plugin only;
  its own loader retains the last valid rules on malformed/partial saves.
- Native fullscreen detection uses the existing status loop; it adds no thread.
  Animation samples use timers at most 30 times per second while moving, with
  no per-frame loop between idle micro-behaviors.

Validation and source/build hashes are recorded under `tasks/mochi-mood/`.
