from __future__ import annotations

from datetime import datetime, timezone
import uuid


STATE_EVENT_TYPES = (
    'student.question_received',
    'bandit.candidates_scored',
    'bandit.prompt_selected',
    'control.baseline_prompt_selected',
    'llm.adaptive_started',
    'llm.adaptive_completed',
    'llm.baseline_started',
    'llm.baseline_completed',
    'turn.persisted',
    'feedback.recorded',
    'qscore.evaluated',
    'bandit.reward_applied',
    'bandit.arm_state_updated',
    'drift.run_completed',
    'drift.signal_detected',
    'drift.ga_triggered',
    'ga.variants_generated',
    'ga.prompt_promoted',
    'pipeline.error',
)


def build_state_event(
    *,
    event_type: str,
    conversation_id: str,
    user_id: str,
    trace_id: str,
    node: str,
    payload: dict | None = None,
    edge: dict | None = None,
    turn_id: str | None = None,
    turn_index: int | None = None,
) -> dict:
    if event_type not in STATE_EVENT_TYPES:
        raise ValueError(f'Unsupported event type: {event_type}')

    event = {
        'event_id': str(uuid.uuid4()),
        'event_type': event_type,
        'occurred_at': datetime.now(timezone.utc).isoformat(),
        'conversation_id': conversation_id,
        'user_id': user_id,
        'turn_id': turn_id,
        'turn_index': turn_index,
        'node': node,
        'edge': edge,
        'payload': payload or {},
        'trace_id': trace_id,
    }
    return event
