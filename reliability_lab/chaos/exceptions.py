"""Exceptions for Controlled Chaos Injection.

Defines deterministic, typed exceptions for failure simulation and safety boundaries.
"""


class ChaosError(Exception):
    """Base exception for all controlled chaos simulation errors."""


class ChaosTimeoutError(ChaosError, TimeoutError):
    """Raised deterministically when TIMEOUT chaos mode is active.

    Subclasses built-in TimeoutError so standard timeout handling catches it.
    """


class ChaosRateLimitError(ChaosError):
    """Raised deterministically when RATE_LIMIT (429) chaos mode is active."""

    def __init__(self, message: str = "Rate limit exceeded: 429 Too Many Requests", status_code: int = 429) -> None:
        super().__init__(message)
        self.status_code = status_code


class UnapprovedToolError(ChaosError, ValueError):
    """Raised when an unapproved or production tool is passed to ChaosProxy.

    Enforces the production-safety boundary.
    """
