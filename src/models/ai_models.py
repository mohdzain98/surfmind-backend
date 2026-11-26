# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

from enum import Enum


class Models(str, Enum):
    """
    Enum representing supported LLM providers.
    Provides helper methods to retrieve the default and alternative model.
    """

    GPT = "gpt"
    GEMINI = "gemini"

    @classmethod
    def default(cls) -> "Models":
        """Return the default model provider."""
        return cls.GEMINI

    @classmethod
    def other(cls) -> "Models":
        """Return the alternative model provider."""
        return cls.GPT


class Embeddings(str, Enum):
    """
    Enum representing supported Embeddings providers.
    """

    GPT = "text-embedding-3-small"
    GEMINI = "models/gemini-embedding-001"

    @classmethod
    def default(cls) -> "Models":
        """Return the default model provider."""
        return cls.GPT

    @classmethod
    def other(cls) -> "Models":
        """Return the alternative model provider."""
        return cls.GEMINI
