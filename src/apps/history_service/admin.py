from django.contrib import admin

from apps.history_service.models import Conversation, Turn


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_id', 'created_at', 'updated_at')
    search_fields = ('id', 'user_id')


@admin.register(Turn)
class TurnAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'turn_index', 'created_at', 'prompt')
    list_filter = ('conversation',)
    search_fields = ('conversation__id', 'user_text', 'assistant_text')

# Register your models here.
