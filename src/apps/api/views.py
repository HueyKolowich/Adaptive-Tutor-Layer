from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.handler.service import TutorResponseHandler
from apps.ratings_service.service import RatingsService
from common.errors import (
    LLMUpstreamError,
    PersistenceError,
    PromptDataError,
    PromptNotFoundError,
)
from .serializers import TurnFeedbackRequestSerializer, TutorRespondRequestSerializer


@method_decorator(csrf_exempt, name='dispatch')
class TutorRespondView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = TutorRespondRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        conversation_id = data.get('conversation_id') or None
        handler = TutorResponseHandler()

        try:
            result = handler.generate_response(
                user_id=data['user_id'],
                conversation_id=conversation_id,
                question_text=data['question_text'],
            )
        except PromptNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except PromptDataError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except LLMUpstreamError as exc:
            return Response(
                {'detail': str(exc), 'status': exc.status, 'body': exc.body},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except PersistenceError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(
            {
                'conversation_id': result['conversation_id'],
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

        ratings_service = RatingsService()
        try:
            feedback, evaluation = ratings_service.record_feedback_and_evaluate(
                turn_id=turn_id,
                user_id=data['user_id'],
                rating_correctness=data['rating_correctness'],
                rating_helpfulness=data['rating_helpfulness'],
                rating_clarity=data['rating_clarity'],
                free_text=data.get('free_text'),
            )
        except PersistenceError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # safeguard
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


def app_view(request):
    return render(request, 'app/index.html')
