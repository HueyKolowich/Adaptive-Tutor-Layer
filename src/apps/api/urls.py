from django.urls import path

from apps.api.views import (
    ConversationHistoryView,
    ConversationListView,
    TurnFeedbackView,
    TutorRespondView,
)

urlpatterns = [
    path('tutor/respond', TutorRespondView.as_view(), name='tutor-respond'),
    path('conversations', ConversationListView.as_view(), name='conversation-list'),
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
