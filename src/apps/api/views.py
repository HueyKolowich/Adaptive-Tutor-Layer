from __future__ import annotations

import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.drift_detection_service.models import DriftSignal
from apps.drift_detection_service.service import DriftDetectionService
from apps.ga_service.service import GAService
from apps.prompt_service.models import Prompt
from apps.handler.service import TutorResponseHandler
from apps.ratings_service.service import RatingsService
from common.errors import (
    FeedbackRequiredError,
    LLMUpstreamError,
    PersistenceError,
    PromptDataError,
    PromptNotFoundError,
)
from common.observability import publish_state_event

from .serializers import TurnFeedbackRequestSerializer, TutorRespondRequestSerializer


@method_decorator(csrf_exempt, name='dispatch')
class TutorRespondView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = TutorRespondRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_id = data['user_id']
        conversation_id = data.get('conversation_id') or str(uuid.uuid4())
        question_text = data['question_text']
        trace_id = str(uuid.uuid4())

        publish_state_event(
            event_type='student.question_received',
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            node='student',
            payload={'question_text': question_text[:300]},
        )

        handler = TutorResponseHandler()

        try:
            result = handler.generate_response(
                user_id=user_id,
                conversation_id=conversation_id,
                question_text=question_text,
                trace_id=trace_id,
            )
        except FeedbackRequiredError as exc:
            publish_state_event(
                event_type='pipeline.error',
                conversation_id=conversation_id,
                user_id=user_id,
                trace_id=trace_id,
                node='student',
                payload={
                    'stage': 'feedback_gate',
                    'error_type': type(exc).__name__,
                    'detail': str(exc),
                    'last_turn_id': exc.last_turn_id,
                    'last_turn_index': exc.last_turn_index,
                },
            )
            return Response(
                {
                    'detail': str(exc),
                    'code': 'feedback_required',
                    'last_turn_id': exc.last_turn_id,
                    'last_turn_index': exc.last_turn_index,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except PromptNotFoundError as exc:
            publish_state_event(
                event_type='pipeline.error',
                conversation_id=conversation_id,
                user_id=user_id,
                trace_id=trace_id,
                node='bandit',
                payload={
                    'stage': 'prompt_selection',
                    'error_type': type(exc).__name__,
                    'detail': str(exc),
                },
            )
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except PromptDataError as exc:
            publish_state_event(
                event_type='pipeline.error',
                conversation_id=conversation_id,
                user_id=user_id,
                trace_id=trace_id,
                node='bandit',
                payload={
                    'stage': 'prompt_selection',
                    'error_type': type(exc).__name__,
                    'detail': str(exc),
                },
            )
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except LLMUpstreamError as exc:
            publish_state_event(
                event_type='pipeline.error',
                conversation_id=conversation_id,
                user_id=user_id,
                trace_id=trace_id,
                node='llm',
                payload={
                    'stage': 'llm',
                    'error_type': type(exc).__name__,
                    'detail': str(exc),
                    'status': exc.status,
                },
            )
            return Response(
                {'detail': str(exc), 'status': exc.status, 'body': exc.body},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except PersistenceError as exc:
            publish_state_event(
                event_type='pipeline.error',
                conversation_id=conversation_id,
                user_id=user_id,
                trace_id=trace_id,
                node='adaptive',
                payload={
                    'stage': 'persistence',
                    'error_type': type(exc).__name__,
                    'detail': str(exc),
                },
            )
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(
            {
                'conversation_id': result['conversation_id'],
                'turn_id': result['turn_id'],
                'tutor_response': result['tutor_response'],
                'turn_index': result['turn_index'],
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name='dispatch')
class TurnFeedbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, turn_id):
        serializer = TurnFeedbackRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_id = data['user_id']

        trace_id = str(uuid.uuid4())
        ratings_service = RatingsService()
        try:
            feedback, evaluation = ratings_service.record_feedback_and_evaluate(
                turn_id=turn_id,
                user_id=user_id,
                rating_correctness=data['rating_correctness'],
                rating_helpfulness=data['rating_helpfulness'],
                rating_clarity=data['rating_clarity'],
                free_text=data.get('free_text'),
                trace_id=trace_id,
            )
        except PersistenceError as exc:
            self._emit_feedback_error(
                turn_id=turn_id,
                user_id=user_id,
                trace_id=trace_id,
                stage='feedback_persistence',
                exc=exc,
            )
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # safeguard
            self._emit_feedback_error(
                turn_id=turn_id,
                user_id=user_id,
                trace_id=trace_id,
                stage='feedback_unknown',
                exc=exc,
            )
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(
            {
                'feedback': {
                    'id': str(feedback.id),
                    'turn_id': str(feedback.turn_id),
                    'user_id': feedback.user_id,
                    'rating_correctness': feedback.rating_correctness,
                    'rating_helpfulness': feedback.rating_helpfulness,
                    'rating_clarity': feedback.rating_clarity,
                    'free_text': feedback.free_text,
                    'created_at': feedback.created_at.isoformat(),
                },
                'evaluation': {
                    'id': evaluation.id if evaluation else None,
                    'evaluator_id': evaluation.evaluator_id if evaluation else None,
                    'q_total': evaluation.q_total if evaluation else None,
                    'q_correctness': evaluation.q_correctness if evaluation else None,
                    'q_helpfulness': evaluation.q_helpfulness if evaluation else None,
                    'q_pedagogy': evaluation.q_pedagogy if evaluation else None,
                    'created_at': evaluation.created_at.isoformat() if evaluation else None,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    def _emit_feedback_error(self, turn_id: str, user_id: str, trace_id: str, stage: str, exc: Exception) -> None:
        from apps.history_service.models import Turn as TurnModel

        turn = TurnModel.objects.filter(id=turn_id).only('conversation_id').first()
        if not turn:
            return

        publish_state_event(
            event_type='pipeline.error',
            conversation_id=str(turn.conversation_id),
            user_id=user_id,
            trace_id=trace_id,
            node='qscore',
            turn_id=str(turn_id),
            payload={
                'stage': stage,
                'error_type': type(exc).__name__,
                'detail': str(exc)[:180],
            },
        )


@method_decorator(csrf_exempt, name='dispatch')
class ConversationHistoryView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, conversation_id):
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response({'detail': 'user_id query param required.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.history_service.models import Turn as TurnModel
        from apps.ratings_service.models import TurnFeedback

        turn_records = TurnModel.objects.filter(
            conversation_id=conversation_id,
            conversation__user_id=user_id,
        ).order_by('turn_index')

        result = []
        for turn in turn_records:
            has_feedback = TurnFeedback.objects.filter(turn=turn, user_id=user_id).exists()
            result.append({
                'turn_id': str(turn.id),
                'turn_index': turn.turn_index,
                'user_text': turn.user_text,
                'assistant_text': turn.assistant_text,
                'has_feedback': has_feedback,
            })

        return Response({'turns': result}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class ConversationListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response({'detail': 'user_id query param required.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.history_service.models import Conversation

        conversations = (
            Conversation.objects.filter(user_id=user_id)
            .order_by('-updated_at')
        )

        result = []
        for conv in conversations:
            first_turn = conv.turns.order_by('turn_index').first()
            preview = ''
            if first_turn:
                preview = first_turn.user_text[:80]
                if len(first_turn.user_text) > 80:
                    preview += '…'
            result.append({
                'conversation_id': str(conv.id),
                'preview': preview,
                'created_at': conv.created_at.isoformat(),
                'updated_at': conv.updated_at.isoformat(),
                'turn_count': conv.turns.count(),
            })

        return Response({'conversations': result}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class DriftRunView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        user_id = (request.data.get('user_id') or '').strip()
        if not user_id:
            return Response({'detail': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        run = DriftDetectionService().run_cycle_for_user(user_id=user_id)
        return Response(
            {
                'drift_run_id': run.id,
                'status': run.status,
                'ga_triggered': run.ga_triggered,
                'metrics': run.metrics_json,
                'requested_by': 'dev',
                'user_id': user_id,
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name='dispatch')
class DriftSignalListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        user_id = (request.query_params.get('user_id') or '').strip()
        if not user_id:
            return Response({'detail': 'user_id query param required.'}, status=status.HTTP_400_BAD_REQUEST)

        rows = (
            DriftSignal.objects.select_related('drift_run')
            .filter(subject_user_id=user_id)
            .order_by('-detected_at')[:100]
        )
        result = [
            {
                'id': row.id,
                'drift_run_id': row.drift_run_id,
                'subject_user_id': row.subject_user_id,
                'signal_type': row.signal_type,
                'severity': row.severity,
                'score': row.score,
                'threshold': row.threshold,
                'scope': row.scope,
                'detected_at': row.detected_at.isoformat(),
                'metadata': row.metadata_json,
            }
            for row in rows
        ]
        return Response({'signals': result}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class GAEvolveView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        user_id = (request.data.get('user_id') or '').strip()
        if not user_id:
            return Response({'detail': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        parent_prompt_id = request.data.get('parent_prompt_id')
        parent_prompt_id_val = int(parent_prompt_id) if parent_prompt_id is not None else None

        k = int(request.data.get('k', 3))
        drift_signal_id = request.data.get('drift_signal_id')
        rows = GAService().generate_variants(
            parent_prompt_id=parent_prompt_id_val,
            subject_user_id=user_id,
            drift_signal_id=int(drift_signal_id) if drift_signal_id is not None else None,
            k=k,
        )
        return Response(
            {
                'user_id': user_id,
                'generated': len(rows),
                'candidate_prompt_ids': [row.prompt_id for row in rows if row.prompt_id],
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name='dispatch')
class PromptLifecycleView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, prompt_id, action):
        user_id = (request.data.get('user_id') or '').strip()
        if not user_id:
            return Response({'detail': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        prompt = Prompt.objects.filter(id=prompt_id).first()
        if prompt is None:
            return Response({'detail': 'prompt not found.'}, status=status.HTTP_404_NOT_FOUND)
        if prompt.owner_user_id and prompt.owner_user_id != user_id:
            return Response({'detail': 'prompt owner mismatch.'}, status=status.HTTP_403_FORBIDDEN)

        if action == 'promote':
            prompt.status = 'active'
            prompt.rollout_pct = 1.0
            prompt.is_active = True
            prompt.save(update_fields=['status', 'rollout_pct', 'is_active'])
            publish_state_event(
                event_type='ga.prompt_promoted',
                conversation_id=f'user:{user_id}',
                user_id=user_id,
                trace_id=str(uuid.uuid4()),
                node='ga',
                edge={'from': 'ga', 'to': 'policies'},
                payload={
                    'prompt_id': prompt.id,
                    'subject_user_id': prompt.owner_user_id or user_id,
                    'status': prompt.status,
                },
            )
        elif action == 'retire':
            prompt.status = 'retired'
            prompt.is_active = False
            prompt.save(update_fields=['status', 'is_active'])
        else:
            return Response({'detail': 'unsupported action.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'prompt_id': prompt.id,
                'status': prompt.status,
                'is_active': prompt.is_active,
                'owner_user_id': prompt.owner_user_id,
            },
            status=status.HTTP_200_OK,
        )


@login_required
def app_view(request):
    return render(request, 'app/index.html')


def ninja_panel_view(request):
    target = settings.NINJA_PANEL_URL
    parsed = urlsplit(target)
    incoming_params = dict(parse_qsl(request.META.get('QUERY_STRING', ''), keep_blank_values=True))
    existing_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing_params.update(incoming_params)

    redirect_url = urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path or '/',
        urlencode(existing_params),
        parsed.fragment,
    ))
    return HttpResponseRedirect(redirect_url)
