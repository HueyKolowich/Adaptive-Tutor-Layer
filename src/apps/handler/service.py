import uuid

from apps.history_service.service import HistoryService
from apps.llm_service.service import LLMService
from apps.prompt_service.service import PromptService
from common.types import PromptContext


class TutorResponseHandler:
    def __init__(
        self,
        prompt_service: PromptService | None = None,
        history_service: HistoryService | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        self.prompt_service = prompt_service or PromptService()
        self.history_service = history_service or HistoryService()
        self.llm_service = llm_service or LLMService()

    def generate_response(
        self,
        user_id: str,
        conversation_id: str | None,
        question_text: str,
    ) -> dict:
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        prompt_context = PromptContext(user_id=user_id, conversation_id=conversation_id)
        system_prompt = self.prompt_service.select_system_prompt(prompt_context)
        history = self.history_service.get_history(conversation_id, user_id)

        llm_response = self.llm_service.generate(
            system_prompt_text=system_prompt.text,
            history_turns=history,
            user_message=question_text,
        )

        metadata = {**(llm_response.get('metadata') or {}), 'prompt_id': system_prompt.prompt_id}
        turn = self.history_service.append_turn(
            conversation_id=conversation_id,
            user_id=user_id,
            user_text=question_text,
            assistant_text=llm_response.get('assistant_text', ''),
            metadata=metadata,
            prompt_id=system_prompt.prompt_id,
        )

        return {
            'conversation_id': conversation_id,
            'turn_index': turn.turn_index,
            'tutor_response': llm_response.get('assistant_text', ''),
        }
