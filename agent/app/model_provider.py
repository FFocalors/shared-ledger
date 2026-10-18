"""P1-02 disabled provider port implementation; it never contacts LM Studio."""

from __future__ import annotations

from .ports import ProviderHealth


class DisabledModelProvider:
    def start(self) -> None:
        pass

    def health(self) -> ProviderHealth:
        return ProviderHealth(status="disabled", inference_available=False)

    def close(self) -> None:
        pass
