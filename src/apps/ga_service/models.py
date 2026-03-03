from django.db import models


class PromptEvolutionRun(models.Model):
    STATUS_CHOICES = (
        ('running', 'running'),
        ('completed', 'completed'),
        ('failed', 'failed'),
    )

    parent_prompt = models.ForeignKey(
        'prompt_service.Prompt',
        on_delete=models.CASCADE,
        related_name='evolution_runs',
    )
    drift_signal = models.ForeignKey(
        'drift_detection_service.DriftSignal',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='evolution_runs',
    )
    requested_by = models.CharField(max_length=32, default='system')
    subject_user_id = models.CharField(max_length=128, default='legacy-global', db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='running')
    generated_count = models.IntegerField(default=0)
    published_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"PromptEvolutionRun(parent={self.parent_prompt_id}, status={self.status})"


class PromptVariantCandidate(models.Model):
    STATUS_CHOICES = (
        ('generated', 'generated'),
        ('published', 'published'),
        ('rejected', 'rejected'),
    )

    evolution_run = models.ForeignKey(
        PromptEvolutionRun,
        on_delete=models.CASCADE,
        related_name='candidates',
    )
    prompt = models.ForeignKey(
        'prompt_service.Prompt',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='variant_candidates',
    )
    text = models.TextField()
    mutation_operator = models.CharField(max_length=64)
    score = models.FloatField(default=0.0)
    passed_safety = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='generated')
    metadata_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"PromptVariantCandidate({self.mutation_operator}, {self.status})"
