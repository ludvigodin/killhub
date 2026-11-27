"""Shared explore/harness errors."""

from __future__ import annotations


class HarnessError(Exception):
    """msb / host / path-policy failure — fail closed, never invent success."""

    def __init__(self, message: str, *, code: str = "harness_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code
