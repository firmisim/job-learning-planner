from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ErrorCategory = Literal["validation", "conflict", "system"]


@dataclass
class ApplicationError(RuntimeError):
    """A safe, operation-scoped error that may cross into the UI layer."""

    category: ErrorCategory
    operation: str
    public_message: str

    def __str__(self) -> str:
        return self.public_message
