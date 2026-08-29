"""Plot registry and batch execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from quant_report_hub.context import CompareContext, PlotContext
from quant_report_hub.plots import compare, diagnostic, portfolio, spread, trades
from quant_report_hub.plots.equity import charts as equity

PlotFn = Callable[[PlotContext], Path | list[Path] | None]


def _collect(result: Path | list[Path] | None, acc: list[Path]) -> None:
    if result is None:
        return
    if isinstance(result, list):
        acc.extend(result)
    else:
        acc.append(result)


PLOT_REGISTRY: dict[str, PlotFn] = {
    "01": portfolio.plot_01_nav_drawdown,
    "02": portfolio.plot_02_daily_pnl_dist,
    "03": spread.plot_03_spread_nav,
    "04": portfolio.plot_04_commission_vs_pnl,
    "05": portfolio.plot_05_activity,
    "06": trades.plot_06_roundtrip,
    "07": spread.plot_07_spread_rank,
    "08": diagnostic.plot_08_zscore,
    "09": trades.plot_09_signal_fill,
    "10": diagnostic.plot_10_oi_filter,
    "11": diagnostic.plot_11_roll_events,
    "12": portfolio.plot_12_monthly,
    "13": portfolio.plot_13_rolling,
    "15": spread.plot_15_correlation,
    "16": equity.plot_16_ic_summary,
    "17": equity.plot_17_synthesis_compare,
    "18": equity.plot_18_factor_ic_bar,
    "19": equity.plot_19_quantile_spread,
}


def run_plots(ctx: PlotContext, plot_ids: tuple[str, ...]) -> list[Path]:
    outputs: list[Path] = []
    for pid in plot_ids:
        fn = PLOT_REGISTRY.get(pid)
        if fn is None:
            continue
        _collect(fn(ctx), outputs)
    return outputs


def run_compare(ctx: CompareContext) -> list[Path]:
    return compare.plot_14_multi_run(ctx)


__all__ = ["PLOT_REGISTRY", "run_compare", "run_plots"]
