from __future__ import annotations


class StarfishDomainError(Exception):
    """Base exception type for domain-level service errors."""


class MapNotFoundError(StarfishDomainError):
    """Raised when requested map payload does not exist."""


class TaskNotFoundError(StarfishDomainError):
    """Raised when requested async task does not exist."""
