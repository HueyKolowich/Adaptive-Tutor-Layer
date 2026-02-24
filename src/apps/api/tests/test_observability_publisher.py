import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from common.observability import publisher as publisher_module
from common.observability.publisher import EventPublishError, publish_state_event


class FakeRedis:
    def __init__(self):
        self.entries = []

    def xadd(self, stream, fields, maxlen=None, approximate=None):
        self.entries.append(
            {
                'stream': stream,
                'fields': fields,
                'maxlen': maxlen,
                'approximate': approximate,
            }
        )


class ObservabilityPublisherTests(SimpleTestCase):
    def tearDown(self):
        publisher_module._publisher.cache_clear()

    @override_settings(
        OBSERVABILITY_MODE=True,
        OBS_EVENTS_STRICT=True,
        OBS_REDIS_URL='redis://fake:6379/0',
        OBS_REDIS_STREAM_KEY='atl:state-events',
        OBS_REDIS_MAXLEN=50,
    )
    def test_redis_publish_success(self):
        fake_redis = FakeRedis()

        with patch('common.observability.publisher._redis_from_url', return_value=fake_redis):
            publish_state_event(
                event_type='student.question_received',
                conversation_id='conv-1',
                user_id='learner-1',
                trace_id='trace-1',
                node='student',
                payload={'question_text': 'What is backprop?'},
            )

        self.assertEqual(len(fake_redis.entries), 1)
        row = fake_redis.entries[0]
        self.assertEqual(row['stream'], 'atl:state-events')
        event = json.loads(row['fields']['event'])
        self.assertEqual(event['event_type'], 'student.question_received')
        self.assertEqual(event['conversation_id'], 'conv-1')

    @override_settings(
        OBSERVABILITY_MODE=True,
        OBS_EVENTS_STRICT=True,
        OBS_REDIS_URL='redis://fake:6379/0',
        OBS_REDIS_STREAM_KEY='atl:state-events',
        OBS_REDIS_MAXLEN=50,
    )
    def test_strict_mode_raises_on_publish_failure(self):
        class BrokenRedis:
            def xadd(self, *args, **kwargs):
                raise RuntimeError('boom')

        with patch('common.observability.publisher._redis_from_url', return_value=BrokenRedis()):
            with self.assertRaises(EventPublishError):
                publish_state_event(
                    event_type='student.question_received',
                    conversation_id='conv-1',
                    user_id='learner-1',
                    trace_id='trace-1',
                    node='student',
                    payload={'question_text': 'x'},
                )

    @override_settings(
        OBSERVABILITY_MODE=True,
        OBS_EVENTS_STRICT=False,
        OBS_REDIS_URL='redis://fake:6379/0',
        OBS_REDIS_STREAM_KEY='atl:state-events',
        OBS_REDIS_MAXLEN=50,
    )
    def test_non_strict_mode_drops_publish_failure(self):
        class BrokenRedis:
            def xadd(self, *args, **kwargs):
                raise RuntimeError('boom')

        with patch('common.observability.publisher._redis_from_url', return_value=BrokenRedis()):
            publish_state_event(
                event_type='student.question_received',
                conversation_id='conv-1',
                user_id='learner-1',
                trace_id='trace-1',
                node='student',
                payload={'question_text': 'x'},
            )
