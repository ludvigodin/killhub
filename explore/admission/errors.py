"""Admission rejection and store failures (D40)."""

from __future__ import annotations


class AdmissionRejected(Exception):
    """Reject create / inference with an HTTP status + public error code."""

    def __init__(self, message: str, code: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class AdmissionStoreError(RuntimeError):
    """Misconfiguration or backend failure (fail closed when Valkey is required)."""
