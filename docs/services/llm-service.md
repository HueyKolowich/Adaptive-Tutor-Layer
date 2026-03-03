# LLM Service

File: `src/apps/llm_service/service.py`

## Purpose
Wraps upstream chat-completions API (Grok endpoint by default) behind a stable internal interface.

## Interface
`generate(system_prompt_text, history_turns, user_message) -> dict`

## Behavior
- Builds messages sequence: system + prior turns + current user message.
- Calls configured upstream URL with model/temperature/max tokens.
- Returns:
  - `assistant_text`
  - `raw_response`
  - metadata (`model`, `temperature`, `max_tokens`, `x_request_id`)

## Errors
Raises `LLMUpstreamError` for HTTP or transport failures.
