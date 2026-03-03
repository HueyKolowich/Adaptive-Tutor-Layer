from django.db import models


class DriftRun(models.Model):
    STATUS_CHOICES = (
        ('running', 'running'),
        ('completed', 'completed'),
        ('failed', 'failed'),
    )

    scope = models.CharField(max_length=64, default='global', db_index=True)
    subject_user_id = models.CharField(max_length=128, default='legacy-global', db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='running')
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    metrics_json = models.JSONField(default=dict)
    ga_triggered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-started_at', '-id']
        indexes = [
            models.Index(fields=('subject_user_id', 'started_at')),
            models.Index(fields=('subject_user_id', 'ga_triggered', 'started_at')),
        ]

    def __str__(self):
        return f"DriftRun({self.scope}, {self.status})"


class DriftSignal(models.Model):
    SEVERITY_CHOICES = (
        ('low', 'low'),
        ('medium', 'medium'),
        ('high', 'high'),
    )

    SIGNAL_CHOICES = (
        ('embedding_centroid_shift', 'embedding_centroid_shift'),
        ('qscore_degradation', 'qscore_degradation'),
        ('feedback_deterioration', 'feedback_deterioration'),
    )

    drift_run = models.ForeignKey(
        DriftRun,
        on_delete=models.CASCADE,
        related_name='signals',
    )
    signal_type = models.CharField(max_length=64, choices=SIGNAL_CHOICES)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES)
    score = models.FloatField()
    threshold = models.FloatField()
    scope = models.CharField(max_length=64, default='global', db_index=True)
    subject_user_id = models.CharField(max_length=128, default='legacy-global', db_index=True)
    prompt = models.ForeignKey(
        'prompt_service.Prompt',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='drift_signals',
    )
    metadata_json = models.JSONField(default=dict)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-detected_at', '-id']
        indexes = [
            models.Index(fields=('subject_user_id', 'detected_at')),
        ]

    def __str__(self):
        return f"DriftSignal({self.signal_type}, {self.severity})"
