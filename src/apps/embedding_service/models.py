from django.db import models


class TurnEmbeddingIndex(models.Model):
    DOC_TYPE_CHOICES = (
        ('question', 'question'),
        ('assistant', 'assistant'),
        ('feedback', 'feedback'),
    )

    turn = models.ForeignKey(
        'history_service.Turn',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='embedding_documents',
    )
    feedback = models.ForeignKey(
        'ratings_service.TurnFeedback',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='embedding_documents',
    )
    document_type = models.CharField(max_length=16, choices=DOC_TYPE_CHOICES)
    vector_id = models.CharField(max_length=128, unique=True)
    embedding_model_version = models.CharField(max_length=64)
    embedding_json = models.JSONField(default=list)
    metadata_json = models.JSONField(default=dict)
    last_synced_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"TurnEmbeddingIndex({self.vector_id}, {self.document_type})"


class EmbeddingSyncJob(models.Model):
    STATUS_CHOICES = (
        ('pending', 'pending'),
        ('running', 'running'),
        ('failed', 'failed'),
        ('done', 'done'),
    )

    turn = models.ForeignKey(
        'history_service.Turn',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='embedding_sync_jobs',
    )
    feedback = models.ForeignKey(
        'ratings_service.TurnFeedback',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='embedding_sync_jobs',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending', db_index=True)
    attempts = models.IntegerField(default=0)
    payload_json = models.JSONField(default=dict)
    last_error = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['status', 'created_at', 'id']

    def __str__(self):
        return f"EmbeddingSyncJob({self.id}, {self.status})"
