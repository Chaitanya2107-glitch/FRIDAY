# FRIDAY's AI language and local thinking

`AI_ASSIST_ONLY=true` is the default, including for an existing `.env` without this setting.
`AI_LANGUAGE_ENABLED=true` is also the default. Direct commands use local matchers, learned mappings
and saved routines. When a local matcher misses, AI translates natural language and typos into a
canonical command. That proposal goes back through the local router; it cannot confirm its own
actions or bypass Telegram restrictions. Unsupported/malformed proposals cause no invented execution.
Chat and voice use AI conversation with recent history; Telegram follows chat. Model tools remain
disabled. User-requested excerpts may be included in conversational answers. Background cognition
and notification judgement use **local Ollama only**, even if a cloud provider is requested.

Models have seven permitted purposes:

- **Inquiry:** local Ollama decides whether one new, evidence-cited question is useful now or silence
  is better. It sees bounded past owner dialogue, current attention/integrations, goals/tasks and dated
  future commitments. There is no scheduled evening queue or question quota. Autonomous questions also
  pass notification review and the shared interruption governor, including questions from other features.
  A required-field schema and local duplicate/source checks prevent malformed or repetitive output.
  The local inquiry call has a 50-second total bound, allowing a measured cold model load; delivery
  claims expire after 90 seconds. No fallback scripted question is emitted when reasoning fails.

- **Understanding:** bounded structured translation to a command or an empty string for conversation.
  Every translated command is validated locally. Unknown batch steps prevent the batch from running.
  An extra app to close that the owner did not name is rejected before the translated batch starts.
- **Conversation:** natural replies through the configured language provider, without tools or writes
  to goals, tasks or semantic owner facts. Conversation history still follows the existing chat storage.
  Relevant original owner dialogue is recalled with its question, channel and original date. Questions
  and unclassified utterances are not automatically promoted into facts. These episodes also feed local
  executive reasoning and notification review; conclusions remain separate from the original reports.

- **Wording:** lightly polish a sentence FRIDAY has already written. No conversation history or full
  personal profile is supplied. Unusable output, changed numbers, lost content words, missing names,
  changed negation, tools, empty replies and timeouts keep the original sentence. Confirmation questions,
  structured replies, private command results and keyboard contents keep their exact local wording.
- **Knowledge:** identify an unfamiliar app/topic using a bounded JSON response. Store its description
  and category in the existing knowledge database, then recall it locally. An unknown answer or unavailable
  model leaves FRIDAY saying she doesn't know. Model knowledge can be mistaken; the user's explanations
  remain stored with their separate source.
- **Notification review:** compare a proposed reminder/notice with current dated owner facts,
  memory provenance, reasoning facts, goals/tasks, activity and recent delivery outcomes. This
  purpose can only return a validated notification decision; it cannot select tools or generate
  general replies. Reminder decisions include cited evidence, source/context checks before delivery
  and a durable explanation. Unknown, invalid or unavailable review retains a reminder for retry.
- **Cognitive review:** reconsider a bounded situation of dated owner evidence, goals/tasks, local
  focus and historical workflow receipts. Reuse strict reasoning and critique schemas to produce
  conclusions/proposals or abstain. This purpose cannot extract new owner facts, call tools or
  automatically apply inferred service changes. All reviewed source versions and the durable review
  claim are rechecked before an atomic report/completion commit. Background inference has a 25-second
  total budget, with eight-second local attempts (plus the existing local startup allowance).
  It starts at most once per five minutes and four
  times per rolling hour. Its provider schema enforces an empty facts array, including on local models.

Model-generated typing, unscoped model reasoning, AI profile reflection, conversation summarization
and autonomous desktop planning remain disabled in assist-only mode. File/web excerpts can be answered
by the conversational language layer. Screen interpretation and image timetable imports explain their limitation.
No AI key is required for startup. Network-dependent integrations still need their own connections.

## Settings

| Setting | Default | Behavior |
| --- | --- | --- |
| `AI_LANGUAGE_ENABLED` | `true` | AI command interpretation and conversational chat/voice; set false to restore local prepared replies |
| `AI_WORDING_ENABLED` | `true` | Set `false` to use only original remarks |
| `AI_KNOWLEDGE_ENABLED` | `true` | Set `false` to use only existing knowledge and user explanations |
| `AI_WORDING_TIMEOUT_SECONDS` | `8` | Timeout per provider; local startup has its own allowance |
| `COGNITIVE_REVIEW_ENABLED` | `true` | Proposal-only executive review, including assist-only; also respects `REASONING_ENABLED`, cognition and the persisted local review switch |
| `NOTIFICATION_REVIEW_ENABLED` | `true` | Brain review for notifications, including assist-only mode; disabling holds reminders and silences optional candidates |
| `NOTIFICATION_REVIEW_TIMEOUT_SECONDS` | `20` | Bounded provider call for a notification decision |
| `NOTIFICATION_REVIEW_RETRY_SECONDS` | `60` | Default reminder re-review delay; validated decisions may select 30–3600 seconds |
| `OLLAMA_AUTO_START` | `true` | Start an installed local Ollama silently on demand |
| `OLLAMA_START_TIMEOUT_SECONDS` | `10` | Maximum wait for the local server to become ready |
| `OLLAMA_IDLE_SECONDS` | `300` | Stop FRIDAY's owned server after this much inactivity |

Set language, wording, knowledge, notification-review and cognitive-review switches to `false` for entirely model-free operation.
Core local commands still work; reminders remain pending while notification review is unavailable or disabled.
Restart FRIDAY after changing settings. The notification-review purpose was explicitly authorized on 2026-10-16;
the owner authorized AI language understanding/conversation and local-only background thinking on 2026-10-20.
The owner authorized the cognitive-review purpose on 2026-10-19. `executive review off` pauses it
persistently; on/off does not reset budgets. `executive status` shows effective availability. Reviews
defer while gaming/busy or during speech/pending questions. A stopped/sleeping laptop performs no review;
the watcher reconciles changed context when running again. No screenshot, clipboard, note contents or
project filesystem paths are supplied by this new purpose. Saved owner facts/task text retain their
existing privacy and redaction rules. Historical execution verification does not establish current app state.
`AI_ASSIST_ONLY=false` retains the earlier model features for compatibility/testing; keep it `true` for the policy above.

## Ollama lifecycle

For language, wording and knowledge online, configured OpenRouter is tried before Ollama.
Offline, cloud providers are skipped. Inquiry, cognitive and notification reviews always use Ollama alone.
A timeout on one provider still allows the fallback to run. Only OpenRouter and Ollama are in this chain.
FRIDAY starts `ollama serve` only for a local HTTP endpoint and reuses a reachable server.
It never installs Ollama or pulls models automatically. Missing executables, startup failures or missing models
leave the language AI unavailable (direct commands still work), or background review pending.
In-flight requests prevent idle shutdown; the idle clock resets when they finish.
Startup failures have a short retry cooldown.

The process and model runners started by FRIDAY are stopped on inactivity and graceful backend shutdown.
An Ollama server started independently is left running; the requests use Ollama's `keep_alive` parameter so
loaded models can still leave memory after inactivity ([Ollama API reference](https://docs.ollama.com/api/chat)).
Knowledge and remarks remain available after the server stops.
