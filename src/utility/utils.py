# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

"""Utility helpers for loading prompt templates and configuration.
Keeps file access centralized for the backend services.
"""

import os
import yaml
from src.utility.path_finder import Finder
from src.utility.logger import AppLogger

logger = AppLogger.get_logger(__name__)


class Utility:
    """Lightweight helper for shared utility operations."""

    def __init__(self):
        """Initialize the utility with a path resolver.
        Keeps filesystem access consistent across services.
        """
        self.paths = Finder()

    def load_prompts(self, filepath="prompts.yml"):
        """
        Load prompt templates from the config directory.
        Resolves the prompts path and parses YAML safely.
        """
        base_path = self.paths.get_directory(name="config")
        full_path = os.path.join(base_path, filepath)
        try:
            with open(full_path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Unable to open file: {e}")
