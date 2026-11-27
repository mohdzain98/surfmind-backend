# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

from src.handlers.mappers import OpenAIExceptionMapper, GeminiExceptionMapper


class LLMExceptionHandler:

    def __init__(self):
        self._mappers = [
            OpenAIExceptionMapper(),
            GeminiExceptionMapper(),
        ]

    def map_exception(self, exc: Exception) -> dict:
        real_exc = exc.__cause__ or exc

        for mapper in self._mappers:
            if mapper.can_handle(real_exc):
                return mapper.map(real_exc)

        return {
            "message": "Unexpected AI error occurred.",
            "code": "UNKNOWN_ERROR",
        }


# singleton instance
llm_exc_handler = LLMExceptionHandler()
