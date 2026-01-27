class PromptNotFoundError(Exception):
    pass


class PromptDataError(Exception):
    pass


class LLMUpstreamError(Exception):
    def __init__(self, status, message, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class PersistenceError(Exception):
    pass


class FeedbackRequiredError(Exception):
    def __init__(self, message: str, last_turn_id: str | None = None, last_turn_index: int | None = None):
        super().__init__(message)
        self.last_turn_id = last_turn_id
        self.last_turn_index = last_turn_index
