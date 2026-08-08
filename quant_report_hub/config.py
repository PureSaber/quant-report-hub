"""Default config and plot group constants."""
from __future__ import annotations

from dataclasses import dataclass, field

TRADING_DAYS = 244
ANNUAL_DAYS = 252

SPREAD_PLOT_GROUPS: dict[str, tuple[str, ...]] = {
    "common": ("01", "02", "12", "13"),
    "universe": ("01", "02", "03", "04", "05", "06", "07", "12", "13", "15"),
    "diagnostic": ("08", "09", "10", "11"),
    "all": tuple(f"{i:02d}" for i in range(1, 16)),
}

EQUITY_PLOT_GROUPS: dict[str, tuple[str, ...]] = {
    "common": ("01", "02", "12", "13"),
    "equity": ("01", "02", "12", "13", "16", "17", "18", "19"),
    "all": ("01", "02", "12", "13", "16", "17", "18", "19"),
}

PLOT_GROUPS = SPREAD_PLOT_GROUPS


@dataclass
class VizConfig:
    output_root: str
    run_id: str
    out_dir: str
    adapter: str = "spread"
    market_root: str = ""
    years: list[str] = field(default_factory=list)
    strategy_params: dict[str, float] = field(default_factory=dict)
    dpi: int = 120
    top_n: int = 10
    rolling_windows: tuple[int, ...] = (60, 120)
    figsize_wide: tuple[float, float] = (12.0, 5.0)
    figsize_tall: tuple[float, float] = (12.0, 8.0)

    def __post_init__(self) -> None:
        if not self.strategy_params:
            self.strategy_params = {
                "lookback": 300.0,
                "entry_z": 3.5,
                "exit_z": 0.0,
            }


def plot_groups_for(adapter: str) -> dict[str, tuple[str, ...]]:
    if adapter == "equity":
        return EQUITY_PLOT_GROUPS
    return SPREAD_PLOT_GROUPS


__all__ = [
    "ANNUAL_DAYS",
    "EQUITY_PLOT_GROUPS",
    "PLOT_GROUPS",
    "SPREAD_PLOT_GROUPS",
    "TRADING_DAYS",
    "VizConfig",
    "plot_groups_for",
]
