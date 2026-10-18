"""Health-only gateway port; business proposal flows are not installed."""

from __future__ import annotations

from .ports import ComponentHealth


class UnimplementedGateway:
    def health(self) -> ComponentHealth:
        return ComponentHealth(status="not_implemented", available=False)
