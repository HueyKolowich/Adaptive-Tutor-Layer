from django.db import models


class Prompt(models.Model):
    text = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    policy_tags_json = models.JSONField(default=dict)
    parent_prompt = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='child_prompts',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"Prompt(active={self.is_active})"
