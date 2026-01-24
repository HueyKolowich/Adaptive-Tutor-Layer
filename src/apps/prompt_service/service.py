from apps.prompt_service.models import Prompt
from common.errors import PromptDataError, PromptNotFoundError
from common.types import PromptContext, SystemPrompt


class PromptService:
    def select_system_prompt(self, context: PromptContext) -> SystemPrompt:
        del context
        active_prompts = Prompt.objects.filter(is_active=True).order_by(
            '-created_at', '-id'
        )
        latest = active_prompts.first()
        if not latest:
            raise PromptNotFoundError("No active prompts found.")

        return SystemPrompt(
            prompt_id=latest.id,
            text=latest.text,
        )
