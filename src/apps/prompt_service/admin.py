from django.contrib import admin

from apps.prompt_service.models import Prompt


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display = ('id', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('text',)

# Register your models here.
