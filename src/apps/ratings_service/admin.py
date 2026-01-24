from django.contrib import admin

from apps.ratings_service.models import Evaluator, TurnEvaluation, TurnFeedback


@admin.register(TurnFeedback)
class TurnFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        'turn',
        'user_id',
        'rating_correctness',
        'rating_helpfulness',
        'rating_clarity',
        'created_at',
    )
    list_filter = ('rating_correctness', 'rating_helpfulness', 'rating_clarity')
    search_fields = ('turn__id', 'user_id', 'free_text')


@admin.register(Evaluator)
class EvaluatorAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'created_at')
    search_fields = ('name', 'version')


@admin.register(TurnEvaluation)
class TurnEvaluationAdmin(admin.ModelAdmin):
    list_display = ('turn', 'evaluator', 'q_total', 'created_at')
    list_filter = ('evaluator',)
    search_fields = ('turn__id', 'evaluator__name', 'evaluator__version')

# Register your models here.
