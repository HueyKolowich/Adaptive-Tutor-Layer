from django.contrib import admin

from apps.embedding_service.models import EmbeddingSyncJob, TurnEmbeddingIndex


@admin.register(TurnEmbeddingIndex)
class TurnEmbeddingIndexAdmin(admin.ModelAdmin):
    list_display = ('vector_id', 'document_type', 'turn', 'feedback', 'embedding_model_version', 'last_synced_at')
    search_fields = ('vector_id',)
    list_filter = ('document_type', 'embedding_model_version')


@admin.register(EmbeddingSyncJob)
class EmbeddingSyncJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'turn', 'feedback', 'attempts', 'updated_at')
    list_filter = ('status',)
    search_fields = ('id',)
