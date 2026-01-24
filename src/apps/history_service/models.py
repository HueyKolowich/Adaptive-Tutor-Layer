import uuid

from django.db import models


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.CharField(max_length=128, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conversation({self.id})"


class Turn(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='turns',
    )
    turn_index = models.IntegerField()
    user_text = models.TextField()
    assistant_text = models.TextField()
    prompt = models.ForeignKey(
        'prompt_service.Prompt',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='turns',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    metadata_json = models.JSONField(default=dict)

    class Meta:
        unique_together = [('conversation', 'turn_index')]
        ordering = ['turn_index']

    def __str__(self):
        return f"Turn({self.conversation.id}:{self.turn_index})"
