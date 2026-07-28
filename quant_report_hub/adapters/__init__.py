"""Adapter registry."""

from __future__ import annotations

from collections.abc import Callable

from quant_report_hub.adapters.base import OutputAdapter
from quant_report_hub.adapters.equity import get_equity_adapter
from quant_report_hub.adapters.spread import get_spread_adapter

ADAPTERS: dict[str, Callable[..., OutputAdapter]] = {
    "spread": get_spread_adapter,
    "equity": get_equity_adapter,
}


def get_adapter(name: str, **kwargs) -> OutputAdapter:
    factory = ADAPTERS.get(name)
    if factory is None:
        supported = ", ".join(sorted(ADAPTERS))
        raise ValueError(f"Unknown adapter '{name}'. Supported: {supported}")
    return factory(**kwargs)
