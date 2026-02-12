from django.urls import path

from apps.api.views import ConversationHistoryView, TurnFeedbackView, TutorRespondView

urlpatterns = [
    path('tutor/respond', TutorRespondView.as_view(), name='tutor-respond'),
    path(
        'turns/<uuid:turn_id>/feedback',
        TurnFeedbackView.as_view(),
        name='turn-feedback',
    ),
    path(
        'conversations/<uuid:conversation_id>/history',
        ConversationHistoryView.as_view(),
        name='conversation-history',
    ),
]
