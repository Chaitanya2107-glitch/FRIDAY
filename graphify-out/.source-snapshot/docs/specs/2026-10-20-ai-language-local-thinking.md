# AI language with local thinking

The owner reported that FRIDAY could not understand commands and explicitly requested AI for
understanding/conversation while keeping thinking local. This supersedes the former prepared-replies-only policy.

- Default `AI_LANGUAGE_ENABLED=true`, alongside existing `AI_ASSIST_ONLY=true`.
- Known commands retain their local route. Unmatched text, including unfamiliar batches and informal
  phrasing without a recognized command starter, receives bounded structured AI translation.
- Strict output contains only a canonical command string, or an empty string for conversation.
  Re-enter local parsing exactly once. No model tools, confirmations or recursive translation.
- Local commands retain execution checks, pending confirmations, channel ownership and complete-batch
  validation. Translated close requests retain the explicitly named target guard, including in batches.
- Chat and voice use a shared conversational helper with recent history. No local task/goal planning
  or automatic semantic fact extraction occurs in this helper. Telegram follows the chat route.
- Language uses configured OpenRouter with installed Ollama fallback. Preserve configured models,
  credentials and billing choices. Report unavailable language providers clearly; direct commands work.
- Cognitive and notification review use only Ollama. A failed local review never spills into cloud
  inference. Existing budgets, validation, critique and recovery remain in force.
- `AI_LANGUAGE_ENABLED=false` restores prepared replies and disables the two new model purposes.
- Language interpretation has a 22-second total budget, six-second provider attempts plus the existing
  local startup allowance. Conversation has 35 seconds total, ten-second attempts plus startup allowance.

Acceptance: tests cover informal commands, conversation through both entrypoints, invalid model output,
unknown batches without partial execution, confirmations, Telegram restrictions, close-target guards,
language outages, model tools denied, and local-only review after provider failure.
The live probe uses synthetic text and never executes commands or saves memory.

Limit: FRIDAY can interpret more phrasing for implemented capabilities. Unsupported capabilities still
need clarification or implementation; understanding arbitrary text does not add arbitrary computer abilities.
