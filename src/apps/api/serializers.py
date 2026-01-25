from rest_framework import serializers


class TutorRespondRequestSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    conversation_id = serializers.CharField(required=False, allow_blank=True)
    question_text = serializers.CharField()


class TurnFeedbackRequestSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    rating_correctness = serializers.IntegerField(min_value=1, max_value=5)
    rating_helpfulness = serializers.IntegerField(min_value=1, max_value=5)
    rating_clarity = serializers.IntegerField(min_value=1, max_value=5)
    free_text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
