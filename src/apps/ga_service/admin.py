from django.contrib import admin

from apps.ga_service.models import PromptEvolutionRun, PromptVariantCandidate


@admin.register(PromptEvolutionRun)
class PromptEvolutionRunAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'subject_user_id',
        'parent_prompt',
        'status',
        'generated_count',
        'published_count',
        'created_at',
        'completed_at',
    )
    list_filter = ('status', 'requested_by')
    search_fields = ('subject_user_id',)


@admin.register(PromptVariantCandidate)
class PromptVariantCandidateAdmin(admin.ModelAdmin):
    list_display = ('id', 'evolution_run', 'mutation_operator', 'score', 'passed_safety', 'status', 'prompt')
    list_filter = ('status', 'passed_safety', 'mutation_operator')
