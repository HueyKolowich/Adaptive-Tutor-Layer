from __future__ import annotations

from functools import lru_cache
import importlib
import json
import logging
from typing import Protocol

from django.conf import settings

from .events import build_state_event


logger = logging.getLogger(__name__)


class EventPublishError(Exception):
    pass


class EventPublisher(Protocol):
    def publish(self, event: dict) -> None:
        ...


class NoopPublisher:
    def publish(self, event: dict) -> None:  # pragma: no cover
        return None


class RedisStreamPublisher:
    def __init__(self, redis_url: str, stream_key: str, maxlen: int) -> None:
        self.redis_client = _redis_from_url(redis_url)
        self.stream_key = stream_key
        self.maxlen = maxlen

    def publish(self, event: dict) -> None:
        payload = json.dumps(event, separators=(',', ':'))
        self.redis_client.xadd(
            self.stream_key,
            {'event': payload},
            maxlen=self.maxlen,
            approximate=True,
        )


class SafePublisher:
    def __init__(self, publisher: EventPublisher, strict: bool) -> None:
        self.publisher = publisher
        self.strict = strict

    def publish(self, event: dict) -> None:
        try:
            self.publisher.publish(event)
        except Exception as exc:
            if self.strict:
                raise EventPublishError(f"Failed to publish event {event.get('event_type')}") from exc
            logger.warning(
                'Dropping state event due to publish failure type=%s trace_id=%s',
                event.get('event_type'),
                event.get('trace_id'),
                exc_info=exc,
            )


def _redis_from_url(redis_url: str):
    try:
        redis_module = importlib.import_module('redis')
    except ModuleNotFoundError as exc:
        raise EventPublishError(
            'redis package is not installed. Install dependencies from requirements.txt.'
        ) from exc
    return redis_module.Redis.from_url(redis_url, decode_responses=True)


@lru_cache(maxsize=1)
def _publisher() -> SafePublisher:
    if not settings.OBSERVABILITY_MODE:
        return SafePublisher(NoopPublisher(), strict=False)

    publisher = RedisStreamPublisher(
        redis_url=settings.OBS_REDIS_URL,
        stream_key=settings.OBS_REDIS_STREAM_KEY,
        maxlen=settings.OBS_REDIS_MAXLEN,
    )
    return SafePublisher(publisher, strict=settings.OBS_EVENTS_STRICT)


def publish_state_event(
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
    event = build_state_event(
        event_type=event_type,
        conversation_id=conversation_id,
        user_id=user_id,
        trace_id=trace_id,
        node=node,
        payload=payload,
        edge=edge,
        turn_id=turn_id,
        turn_index=turn_index,
    )
    _publisher().publish(event)
    return event
