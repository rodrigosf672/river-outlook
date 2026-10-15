"""Typed failures, so every upstream problem maps to one clear client response."""
from __future__ import annotations


class UpstreamError(Exception):
    """An external API (USGS, Open-Meteo, Runpod) failed or refused us.

    kind is one of: "rate_limited", "unavailable", "not_found", "bad_response".
    """

    def __init__(self, service: str, kind: str, message: str,
                 retry_after: int | None = None) -> None:
        super().__init__(message)
        self.service = service
        self.kind = kind
        self.message = message
        self.retry_after = retry_after


class InputError(Exception):
    """The request is well-formed but cannot be served (e.g. a gauge with no data)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
