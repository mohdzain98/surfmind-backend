# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact


class BaseExceptionMapper:
    def can_handle(self, exc: Exception) -> bool:
        raise NotImplementedError

    def map(self, exc: Exception) -> dict:
        raise NotImplementedError
