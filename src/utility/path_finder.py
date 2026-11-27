# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

"""Resolve important filesystem paths relative to the backend root."""

from pathlib import Path
from src.utility.logger import AppLogger

logger = AppLogger.get_logger(__name__)


class PathResolver:
    """
    Robust folder resolver that always returns correct paths relative to backend root.
    Works from any file, any working directory, any environment.
    """

    # Detect backend root dynamically (backend/)
    BACKEND_ROOT = Path(__file__).resolve().parents[2]
    # utils -> src -> backend

    # Define known directories here
    DIR_MAP = {
        "root": BACKEND_ROOT,
        "data": BACKEND_ROOT / "data",
        "config": BACKEND_ROOT / "config",
        "src": BACKEND_ROOT / "src",
        "prompts": BACKEND_ROOT / "config" / "prompts.yml",
        "logs": BACKEND_ROOT / "data" / "logs",
    }

    @classmethod
    def get(cls, name: str) -> Path:
        """
        Returns absolute path from name key.
        Ensures directory exists if it's a folder.
        """
        if name not in cls.DIR_MAP:
            msg = f"Unknown directory key: '{name}'. Valid keys: {list(cls.DIR_MAP.keys())}"
            logger.error(msg)
            raise KeyError(msg)

        path = cls.DIR_MAP[name]

        # If it's a directory, ensure created
        if path.suffix == "":
            path.mkdir(parents=True, exist_ok=True)

        return path


class Finder:
    """Thin wrapper exposing resolved directories for external callers.

    Delegates actual lookups to PathResolver while keeping a simple interface.
    Safe to reuse anywhere in the backend codebase.
    """

    def __init__(self):
        """Instantiate the finder without additional configuration."""
        pass

    def get_directory(self, name: str) -> Path:
        """Return a resolved, ensured directory path by logical name."""
        return PathResolver.get(name)
