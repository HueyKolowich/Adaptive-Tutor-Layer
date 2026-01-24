from dataclasses import dataclass


@dataclass(frozen=True)
class PromptContext:
    user_id: str
    conversation_id: str | None = None


@dataclass(frozen=True)
class SystemPrompt:
    prompt_id: int
    text: str


@dataclass(frozen=True)
class ChatTurn:
    user_text: str
    assistant_text: str
    turn_index: int
