from django.db import transaction
from django.db.models import Max

from apps.history_service.models import Conversation, Turn
from common.errors import PersistenceError
from common.types import ChatTurn


class HistoryService:
    def get_history(self, conversation_id: str, user_id: str) -> list[ChatTurn]:
        turns = Turn.objects.filter(
            conversation_id=conversation_id,
            conversation__user_id=user_id,
        ).order_by('turn_index')

        return [
            ChatTurn(
                user_text=turn.user_text,
                assistant_text=turn.assistant_text,
                turn_index=turn.turn_index,
            )
            for turn in turns
        ]

    def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        user_text: str,
        assistant_text: str,
        metadata: dict,
        prompt_id: int | None = None,
    ) -> Turn:
        try:
            with transaction.atomic():
                conversation, _ = Conversation.objects.get_or_create(
                    id=conversation_id,
                    defaults={'user_id': user_id},
                )
                if conversation.user_id != user_id:
                    raise PersistenceError("Conversation user_id mismatch.")

                if prompt_id is None:
                    prompt_id = (metadata or {}).get('prompt_id')

                last_turn = (
                    Turn.objects.filter(conversation=conversation)
                    .aggregate(max_index=Max('turn_index'))
                    .get('max_index')
                )
                next_index = 0 if last_turn is None else last_turn + 1
                turn = Turn.objects.create(
                    conversation=conversation,
                    turn_index=next_index,
                    user_text=user_text,
                    assistant_text=assistant_text,
                    prompt_id=prompt_id,
                    metadata_json=metadata or {},
                )
                return turn
        except PersistenceError:
            raise
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc
