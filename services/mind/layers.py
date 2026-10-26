"""Audited foundations, not a claim that naming a layer makes it intelligent."""


def inventory():
    return [
        {"name": "Perception", "modules": ["interfaces/api/routes/chat.py", "services/voice/stt.py", "services/vision/screen.py", "services/mind/brain.py"],
         "limits": "Text, transcribed voice, requested screen images and activity events; no continuous visual understanding."},
        {"name": "Attention", "modules": ["services/mind/thoughts.py", "services/mind/talk.py", "services/mind/notifications.py", "services/mind/executive.py", "services/mind/cognitive_runtime.py", "services/mind/inquiry.py"],
         "limits": "Event-driven attention, versioned evidence review and one-question-or-silence decisions with shared interruption limits; broad autonomous goal pursuit remains deferred."},
        {"name": "Working memory", "modules": ["services/mind/cognition.py", "services/mind/workspace.py", "services/mind/cognition_context.py"],
         "limits": "Shared events, explicit task progress, checkpointed local handoffs and project-session briefs; general automatic multi-tool task tracking is deferred."},
        {"name": "Long-term memory", "modules": ["services/memory/semantic.py", "services/memory/episodes.py", "services/mind/knowledge.py", "services/mind/brain_memory.py", "services/mind/temporal_memory.py"],
         "limits": "Dated dialogue and locally reviewed commitment revisions feed shared situation recall; original-date anchoring, uncertainty and bounded history; interpretations are not verified facts."},
        {"name": "Goals and motivation", "modules": ["services/mind/workspace.py", "services/mind/life.py", "services/mind/life_state.py"],
         "limits": "Shared responsibility/uncertainty focus, contextual timing feedback and independent review/interrupt gates; software prioritization, not human needs or automatic goal pursuit."},
        {"name": "Reasoning and prediction", "modules": ["services/mind/reasoning.py", "services/mind/reasoning_store.py", "services/mind/reasoning_effects.py", "services/mind/foresight.py", "services/mind/notifications.py"],
         "limits": "Evidence-cited facts, consequences, predictions, critique and proposals; supported changes target classes, task plans and reminders. Model checks are fallible; arbitrary tool-plan execution remains deferred."},
        {"name": "Executive control", "modules": ["services/automation/intent.py", "services/computer/agent.py", "services/mind/workspace.py", "services/mind/executive.py"],
         "limits": "Shared request/action-intent/outcome events, feature-write lifecycles, project source checks and confirmations; arbitrary model-generated tool-plan execution remains deferred."},
        {"name": "Action and communication", "modules": ["services/automation/actions.py", "services/voice/tts.py", "services/reminders/service.py", "services/telegram/client.py"],
         "limits": "Existing tools and transports; submission is distinct from user reading or hearing."},
        {"name": "Metacognition and verification", "modules": ["services/computer/agent.py", "services/mind/cognition.py", "services/mind/reviews.py", "services/mind/foresight.py"],
         "limits": "Outcome records, screen rechecks, prediction scores and reviews; no universal independent answer/task verifier yet."},
        {"name": "Learning and adaptation", "modules": ["services/mind/corrections.py", "services/mind/talk.py", "services/mind/learner.py", "services/learning/service.py"],
         "limits": "Corrections, reaction learning and scoped predictive training; no autonomous general model weight updates."},
    ]


def describe():
    return "Ten layer foundations (capabilities differ by layer):\n" + "\n".join(
        f"{i}. {layer['name']}: {layer['limits']}" for i, layer in enumerate(inventory(), 1))
