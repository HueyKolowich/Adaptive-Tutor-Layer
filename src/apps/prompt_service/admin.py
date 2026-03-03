from django.contrib import admin

from apps.prompt_service.models import (
    BanditUserArmState,
    Prompt,
    PromptDecision,
)


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'origin', 'owner_user_id', 'rollout_pct', 'is_active', 'created_at')
    list_filter = ('status', 'origin', 'is_active')
    search_fields = ('text', 'owner_user_id')


@admin.register(PromptDecision)
class PromptDecisionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'learner_id',
        'prompt',
        'conversation_id',
        'turn',
        'turn_number',
        'sampled_theta',
        'reward',
        'model_version',
        'chosen_at',
    )
    list_filter = ('model_version',)
    search_fields = ('learner_id', 'conversation_id', 'prompt__id', 'turn__id')
    readonly_fields = ('chosen_at',)


@admin.register(BanditUserArmState)
class BanditUserArmStateAdmin(admin.ModelAdmin):
    list_display = (
        'learner_id',
        'prompt',
        'mu0',
        'gamma',
        'lambda0',
        'sigma_r',
        'alpha',
        'model_version',
        'updated_at',
    )
    search_fields = ('learner_id', 'prompt__id')
    readonly_fields = ('updated_at',)

# Register your models here.
