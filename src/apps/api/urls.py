from django.urls import path

from apps.api.views import (
    ConversationHistoryView,
    ConversationListView,
    DriftRunView,
    DriftSignalListView,
    GAEvolveView,
    PromptLifecycleView,
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
    path('internal/drift/run', DriftRunView.as_view(), name='drift-run'),
    path('internal/drift/signals', DriftSignalListView.as_view(), name='drift-signals'),
    path('internal/ga/evolve', GAEvolveView.as_view(), name='ga-evolve'),
    path(
        'internal/prompts/<int:prompt_id>/<str:action>',
        PromptLifecycleView.as_view(),
        name='prompt-lifecycle',
    ),
]
