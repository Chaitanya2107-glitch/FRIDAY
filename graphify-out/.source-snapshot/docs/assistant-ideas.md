# FRIDAY: assistant ideas and improvements

Saved 2026-10-15 at the owner's request from the assistant brainstorming session.

## Status and purpose

This preserves the recommendations discussed in the session and adds further candidates.
Saving an idea does not approve its implementation or change FRIDAY's permissions or model policy.
The implementation direction and shipped milestones remain in [assistant-roadmap.md](assistant-roadmap.md).
Current execution work remains in `tasks/plan.md` and `tasks/todo.md`.

The objective is dependable assistance: understand a goal, preserve context, act within the agreed
scope, verify the result, remember progress and follow through. The observations below came from
source/documentation inspection, not a fresh evaluation of the running assistant.

At the first review, the local handoff implementation checklist was open. On saving this document,
the roadmap and checklist record that milestone as completed, with a reported 1,925 passing tests.
That existing verification was not rerun for this documentation change. General multi-tool execution
is still a separate capability from the completed local handoff template.

## Existing foundations and constraint

The repository contains voice interaction, semantic memory, goals/tasks, activity awareness,
proactive notices, file search, Telegram and supervised desktop-control implementations.
Availability depends on configuration, service health and operating policy.

`providers/policy.py` and `core/config.py` default to `AI_ASSIST_ONLY=true`. This limits model use to
optional wording and knowledge lookup; broader model reasoning and desktop planning are gated.
The private configuration and live runtime were not inspected for this brainstorming review.
Any future expansion needs an explicit purpose and scope. Do not silently change that setting.

## Recommendations from the first discussion

| Priority | Improvement | Desired owner experience |
|---|---|---|
| 1 | Reliable task execution | Prepare material for tomorrow's project review, check the agreed output and report unfinished work. |
| 2 | Conversation continuity | Understand "the other PDF", a correction to chapter three, and a subsequent Telegram request as one evolving task. |
| 3 | Consistent personal memory | Distinguish preferences, temporary situations, confirmed facts and guesses; propagate corrections to relevant services. |
| 4 | Application understanding | Identify and interact with documents, browser tabs and application controls. |
| 5 | Natural voice interaction | Handle pauses, interruptions, corrections and resumption without restarting the conversation. |
| 6 | Goal-driven initiative | Offer a useful next step based on commitments, priorities and the current situation. |
| 7 | Learning from demonstrations | Turn a reviewed demonstration into a reusable procedure. |
| 8 | Real assistant evaluations | Measure complete workflows, corrections and failure recovery, alongside software regression tests. |

Execution should progress through supported, verifiable adapters with persistent state,
cancellation and restart recovery. Tool results should determine subsequent steps.
For application control, evaluate native APIs, browser structure and Windows UI Automation,
with screenshots as a fallback appropriate to the application.

### Additional opportunities from the first discussion

1. **Commitment tracker.** Capture reviewable commitments from statements such as "I'll finish this
   tonight"; track postponement, dependencies and completion without treating every sentence as a task.
2. **Persistent project understanding.** Preserve purpose, important files, decisions, next step,
   blockers and last verified progress. Answer "where did we leave FRIDAY?" after time away.
3. **Work-session restoration.** Reopen approved files and links, explain the stopping point and
   offer the next action. Build on existing modes, sessions and project tracking.
4. **Personal research desk.** Combine web research with owner documents, preserve sources and
   unanswered questions, and compare approaches against project constraints and hardware.
5. **Exam-preparation companion.** Connect syllabus, notes, available time and practice results;
   adapt revision to demonstrated understanding.
6. **Calendar and communication coordinator.** Integrate selected calendar/message data so changed
   commitments can affect preparation. Opening a website is distinct from maintaining its events.
7. **Reviewed procedure learning.** Capture a demonstration, let the owner correct its steps and
   define its execution scope; handle changed interfaces and unexpected outcomes explicitly.
8. **Visible activity and task progress.** Expose listening, searching, working, waiting, blocked
   and unverified states with evidence and controls.
9. **Laptop/phone continuity.** Begin with explicit Telegram task handoffs and clarification replies;
   evaluate a dedicated phone companion later. Laptop-hosted services require the laptop to run.
10. **Physical-environment integration.** Consider lights, plugs and sensors when useful hardware
    exists; Home Assistant is an integration candidate, not an installed FRIDAY capability claim.

Useful questions should resolve a current uncertainty, such as available study time or a difficult
topic. Build on the existing training/curiosity systems and retain reviewed answers.

### Proposed flagship experiences and starting order

- **Resume my project:** restore context, identify the blocker, assist with the next supported task
  and preserve a handoff.
- **Prepare for my exam:** gather material, build a manageable plan, run practice and preserve progress.
- **Prepare for tomorrow:** reconcile commitments, identify missing preparation and offer concrete actions.

Initial recommendation: complete and validate the execution foundation, then add reliable conversational
references/corrections and use both for project resumption. The handoff milestone has since been recorded
as completed; the next step is selecting a small supported workflow beyond that template.

Each flagship experience should be evaluated under changed instructions, interruption, provider
failure and restart. Check observable outcomes and usefulness. A generated file existing does not
establish that its contents satisfy the request.

## Further candidates from the second discussion

These extend the first list. They are proposals, not verified absences across every FRIDAY module.
Several can build on existing cognition, learning, health and confirmation services.

### 1. Preview consequences before acting

Example: "What would change if we move this study session to Saturday?"
Show affected commitments, conflicts and proposed changes before applying anything. Start with a
read-only schedule comparison. Any projected benefit or duration estimate must expose its assumptions.
Depends on temporal memory, task state and relevant service adapters.

### 2. Recover from partial success and support undo

Example: a submission folder was created and populated, but report generation failed.
Explain which steps succeeded, resume from the failure and avoid repeating completed side effects.
Where supported, preserve prior state and offer a compensating action, such as restoring moved files.
Some actions cannot be undone; expose that property before execution rather than claiming universal undo.
Depends on verified execution, stable operation IDs and adapter-specific recovery behavior.

### 3. Know live capabilities and limitations

Example: "I can search local notes now; calendar access needs reconnection."
Extend the curated layer inventory into an on-demand capability check covering service reachability,
credentials/configuration availability, supported operations and last successful probe.
An installed package or registered tool is not proof that the capability works.
Start with read-only status for a few existing services. Probe without causing external side effects.

### 4. Produce complete, editable deliverables

Example: "Turn these project notes into a review pack with decisions, missing evidence and next steps."
Extend writing/typing into structured local outputs with templates and validation. Start with Markdown
and the existing handoff machinery; add other file formats only for a concrete owner workflow.
Check required sections and source coverage, alongside whether the output is useful.

### 5. Serve as a personal engineering lab

Example: "Compare these two FRIDAY architectures against my constraints."
Track requirements, alternatives, measurements, experiments and decisions. Use deterministic tools
for calculations and tests; preserve units, inputs, assumptions and results. Separate measured findings
from model suggestions. Start with one existing project and one reproducible experiment.

### 6. Handle mixed-language conversation and personal vocabulary

Example: an explanation contains English technical terms and another language the owner uses.
Evaluate the actual languages, names, accent and switching patterns needed by the owner before choosing
an approach. Preserve exact names, code, dates and amounts during transcription/translation.
Start with an opt-in vocabulary and a small consented evaluation set; existing Hindi TTS fallback alone
does not establish reliable mixed-language conversation.

### 7. Learn how to collaborate with the owner

Example: give a concise hint during a study problem, but a detailed explanation when asked to teach.
Extend personality into explicit, editable preferences for depth, initiative, teaching style and when
to ask questions. Do not infer permanent personality or emotional facts from a single interaction.
Start with a few owner-set preferences and verify their effect on actual conversations.

### 8. Allocate attention and computing resources deliberately

Example: postpone optional indexing or background reasoning while gaming, presenting or on low battery.
Build on existing busy guards, system stats and Ollama lifecycle management. Distinguish urgent requested
work from optional background work; expose delay and resource limits when relevant.
Measure responsiveness and resource use before adding a scheduler or a more complex model router.

### 9. Explain a decision through its evidence

Example: "Why did you suggest this?" -> the relevant owner goal, dated fact and observation.
Extend existing cognition/reasoning records into a concise explanation of evidence, uncertainty,
actions and outcomes. This is a factual decision record, not hidden model reasoning.
Start with a supported notification or task and make the record easy to correct.

### 10. Preserve continuity through backup and restore

Example: move to a new laptop without losing reviewed facts, projects, procedures and preferences.
Create a versioned export with linked artifacts and a verified restore process. Keep secrets in their
proper credential stores and handle missing integrations explicitly after restore.
For live SQLite data, use an appropriate consistent backup mechanism rather than assuming an ordinary
file copy preserves the complete current state. Start with an isolated restore drill.

### 11. Turn demonstrated needs into reviewable new skills

Example: after several uses of the same report workflow, propose a named reusable procedure.
First compose existing supported tools; add a new adapter only when a specific missing operation
requires it. Preview inputs, outputs, scope and verification. Review generated code outside the live
assistant before deployment. Start with a procedure manifest for existing tools, not runtime self-modification.

### 12. Help with meetings and explanations

Example: "Help me prepare for my project viva" -> practice questions, a timed explanation and feedback.
Later, explicitly started meeting sessions could produce reviewed decisions and action items from
consented recordings or transcripts. Start with viva rehearsal using owner-provided material;
do not infer permission for background recording or sharing.

## Prioritizing the second set

Recommended near-term candidates: live capability status, complete local deliverables and partial-failure
recovery. They support the existing execution direction and are useful before a large expansion of integrations.
What-if previews and the engineering lab are promising subsequent experiences. Mixed-language interaction,
meeting capture and physical devices need owner-specific requirements and evaluation before selection.

For any selected candidate, define one concrete request, the expected observable result, allowed data/tools,
failure behavior and a small repeatable evaluation. Keep speculative ideas out of the active task checklist
until an implementation slice is chosen.

## Gesture HUD accessory — saved 2026-10-26

Owner requested preserving this idea for later. Desired effect: a visually impressive,
useful accessory that makes FRIDAY feel dramatically more interactive.

- Explicitly activate a webcam gesture mode with an animated, responsive control overlay.
- Open palm summons the HUD; pinch and move adjusts a floating volume dial.
- Swipe switches tracks or navigates controls; closing a fist dismisses the overlay.
- Point/select a screen region and say "Friday, explain this" to request contextual help.
  Reliable pointing-to-screen mapping is an implementation question to validate.
- Show the recognized gesture and action immediately; begin with a small dependable vocabulary.

This is a saved feature concept, not an implemented capability or approval to build.
The owner wants more ideas with the same visible, exciting accessory feel before choosing.

## References

- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents): simple workflows,
  feedback from tools and explicit stopping conditions.
- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents):
  evaluate actual environment outcomes and interaction quality.
- [Windows UI Automation fundamentals](https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiautocore-overview):
  control information and interaction patterns exposed by applications.
- [LongMemEval](https://arxiv.org/abs/2410.10813): multi-session recall, temporal reasoning, updates and abstention.
- [Home Assistant LLM API](https://developers.home-assistant.io/docs/core/llm/): exposed entities and assistant control.
- [MCP server primitives](https://modelcontextprotocol.io/specification/draft/server/index): tools, resources
  and prompts; a possible future integration boundary, not proof of service availability or permission.
- [SQLite Online Backup API](https://www.sqlite.org/backup.html): consistent backup mechanisms for live databases.
