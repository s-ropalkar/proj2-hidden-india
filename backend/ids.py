"""Simple string IDs for MySQL documents (replaces MongoDB ObjectId)."""

from __future__ import annotations

import uuid


def new_id() -> str:
    return uuid.uuid4().hex


def as_id(value) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
