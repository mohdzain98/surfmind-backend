# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

import google.api_core.exceptions as google_exceptions
from src.handlers.mappers.base_mapper import BaseExceptionMapper


class GeminiExceptionMapper(BaseExceptionMapper):

    def can_handle(self, exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                google_exceptions.ResourceExhausted,
                google_exceptions.Unauthenticated,
            ),
        )

    def map(self, exc: Exception) -> dict:
        if isinstance(exc, google_exceptions.ResourceExhausted):
            return {
                "message": "Gemini quota exceeded.",
                "code": "QUOTA_EXCEEDED",
            }

        if isinstance(exc, google_exceptions.Unauthenticated):
            return {
                "message": "Gemini authentication failed.",
                "code": "AUTH_ERROR",
            }

        return {
            "message": "Gemini error occurred.",
            "code": "GEMINI_ERROR",
        }
