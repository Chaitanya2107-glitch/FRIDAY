# FRIDAY’s emotion and expression

FRIDAY replays local events into four 0–1 dimensions. Valence tracks how bright the tone is, arousal tracks its energy, and the existing warmth and curiosity counters still contribute. The drives describe curiosity, readiness to help, tiredness and a welcome after time away. The distance from baseline halves every three hours. The baseline is valence .54, arousal .36, warmth .45, curiosity .15, readiness to help .50, tiredness .08 and welcome 0.

| Event | Source | Change before decay |
| --- | --- | --- |
| Task finished | A saved workspace completion or a completed focus session | Valence +.20, arousal +.14, warmth +.10 |
| Exam close | A saved exam within 24 hours or an owner-confirmed date-only exam today or tomorrow | Arousal +.10, readiness to help +.24 |
| Praise | Explicit local feedback such as “nice work” | Valence +.17, warmth +.15 |
| Correction | Explicit local wording such as “I meant…” | Arousal −.08, readiness to help +.10 |
| Late night | Recent laptop input between 01:00 and 05:59 local time | Valence −.04, arousal −.12, tiredness +.30 |
| Low battery | An unplugged laptop reaches 20% or below | Valence −.09, arousal +.06, readiness to help +.10 |
| Return after a long absence | An observed idle period of at least an hour followed by activity | Valence +.16, warmth +.16, welcome +.36 |
| Explicit stress | A first-person statement such as “I’m stressed before my exam” | Arousal −.15, warmth +.05, readiness to help +.25 |

Quiet and time away leave warmth alone. An observed return can bring a wave and one welcome when you next say hello in the ten-minute welcome window. An explicit stress statement keeps local replies brief and joke-free for up to six hours. Mochi uses the existing mood priorities for alerts and focus scenes. The existing action and scheduling code owns permissions, confirmations and saved facts.

Use `show your character` to see the five traits and values, or `reset your character` to restore the default trait values. Each trait can drift by at most .10 across any rolling seven days. The local change history records the cue and numeric changes. Humour follows the existing learned dial.

The expression library has a three-day cooldown for rendered variants and jokes. Necessary confirmations and factual fallback text can repeat. With model assistance enabled, Ollama can draft up to 20 lines a day when the laptop is plugged in or has been idle for five minutes. Use `review lines`, `edit line ID: template`, `approve line ID` or `reject line ID`. Editing keeps a draft pending. Approved wording works offline, and turning the model off pauses new drafts.

## Sample day with the model off

| Time | Mood | FRIDAY |
| --- | --- | --- |
| 08:15 | Calm, after explicit exam stress | “Applied Physics exam, Boss, in 20 minutes.” |
| 15:00 | Neutral | “I’m here, Boss. How can I help?” |
| 17:20 | Bright, after a task completion | “Saved your completion report for lab notes.” |
