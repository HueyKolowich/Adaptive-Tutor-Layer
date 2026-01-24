from django.db import models


class TurnFeedback(models.Model):
    turn = models.ForeignKey(
        'history_service.Turn',
        on_delete=models.CASCADE,
        related_name='feedback_entries',
    )
    user_id = models.CharField(max_length=128, db_index=True)
    rating_correctness = models.IntegerField()
    rating_helpfulness = models.IntegerField()
    rating_clarity = models.IntegerField()
    free_text = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TurnFeedback({self.turn_id})"


class Evaluator(models.Model):
    name = models.CharField(max_length=128)
    version = models.CharField(max_length=32)
    config_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Evaluator({self.name}@{self.version})"


class TurnEvaluation(models.Model):
    turn = models.ForeignKey(
        'history_service.Turn',
        on_delete=models.CASCADE,
        related_name='evaluations',
    )
    evaluator = models.ForeignKey(
        Evaluator,
        on_delete=models.CASCADE,
        related_name='turn_evaluations',
    )
    q_total = models.FloatField()
    q_correctness = models.FloatField()
    q_helpfulness = models.FloatField()
    q_pedagogy = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TurnEvaluation({self.turn_id}, {self.evaluator_id})"
