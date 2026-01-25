from django.urls import path

from apps.api.views import TutorRespondView, TurnFeedbackView

urlpatterns = [
    path('tutor/respond', TutorRespondView.as_view(), name='tutor-respond'),
    path(
        'turns/<uuid:turn_id>/feedback',
        TurnFeedbackView.as_view(),
        name='turn-feedback',
    ),
]
