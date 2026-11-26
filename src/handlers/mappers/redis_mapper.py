# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

from redis.exceptions import (
    ConnectionError,
    TimeoutError,
    AuthenticationError,
    RedisError,
)

from src.handlers.mappers.base_mapper import BaseExceptionMapper


class RedisExceptionMapper(BaseExceptionMapper):

    def can_handle(self, exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                ConnectionError,
                TimeoutError,
                AuthenticationError,
                RedisError,
            ),
        )

    def map(self, exc: Exception) -> dict:

        if isinstance(exc, ConnectionError):
            return {
                "message": "Unable to connect to storage service.",
                "code": "REDIS_CONNECTION_ERROR",
            }

        if isinstance(exc, TimeoutError):
            return {
                "message": "Storage service timeout. Please try again.",
                "code": "REDIS_TIMEOUT",
            }

        if isinstance(exc, AuthenticationError):
            return {
                "message": "Storage authentication failed.",
                "code": "REDIS_AUTH_ERROR",
            }

        return {
            "message": "Storage service error occurred.",
            "code": "REDIS_ERROR",
        }
