from django.db import models


class Prompt(models.Model):
    ORIGIN_CHOICES = (
        ('manual', 'manual'),
        ('ga', 'ga'),
    )
    STATUS_CHOICES = (
        ('active', 'active'),
        ('candidate', 'candidate'),
        ('retired', 'retired'),
    )

    text = models.TextField()
    is_active = models.BooleanField(default=True)
    origin = models.CharField(max_length=16, choices=ORIGIN_CHOICES, default='manual')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='active', db_index=True)
    rollout_pct = models.FloatField(default=1.0)
    owner_user_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    policy_tags_json = models.JSONField(default=dict)
    lineage_metadata_json = models.JSONField(default=dict)
    parent_prompt = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='child_prompts',
    )

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=('is_active', 'status', 'owner_user_id')),
        ]

    def __str__(self):
        return f"Prompt(active={self.is_active})"


class PromptDecision(models.Model):
    learner_id = models.CharField(max_length=128, db_index=True)
    conversation_id = models.UUIDField(db_index=True)
    turn = models.ForeignKey(
        'history_service.Turn',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='prompt_decisions',
    )
    prompt = models.ForeignKey(
        Prompt,
        on_delete=models.CASCADE,
        related_name='prompt_decisions',
    )
    turn_number = models.IntegerField()
    sampled_theta = models.FloatField()
    model_version = models.CharField(max_length=32)
    chosen_at = models.DateTimeField(auto_now_add=True)
    reward = models.FloatField(null=True, blank=True)
    reward_computed_at = models.DateTimeField(null=True, blank=True)
    reward_version = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        ordering = ['-chosen_at', '-id']

    def __str__(self):
        return f"PromptDecision(prompt={self.prompt_id}, turn={self.turn_id})"


class BanditUserArmState(models.Model):
    learner_id = models.CharField(max_length=128, db_index=True)
    prompt = models.ForeignKey(
        Prompt,
        on_delete=models.CASCADE,
        related_name='user_bandit_states',
    )
    mu0 = models.FloatField(default=0.5)
    lambda0 = models.FloatField(default=4.0)
    eta = models.FloatField(default=0.0)
    nu = models.FloatField(default=0.0)
    sigma_r = models.FloatField(default=0.2)
    alpha = models.FloatField(default=1.0)
    gamma = models.FloatField(default=0.998)
    effective_n = models.FloatField(default=0.0)
    model_version = models.CharField(max_length=32)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('learner_id', 'prompt'),
                name='unique_learner_prompt_bandit_state',
            ),
        ]

    def __str__(self):
        return f"BanditUserArmState(learner={self.learner_id}, prompt={self.prompt_id})"
