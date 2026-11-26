# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

"""Declarative base for SurfMind's SQLAlchemy ORM models.

Provides the shared metadata object Alembic and all ORM models bind to.
Kept as its own module so migrations can import it without pulling in the
rest of the ORM model definitions.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all SurfMind ORM models."""
