"""Spread adapter parity — canonical implementation in quant-report-hub."""

from __future__ import annotations

from quant_report_hub.adapters.spread import SpreadAdapter
from quant_report_hub.config import SPREAD_PLOT_GROUPS, plot_groups_for
from quant_report_hub.plots.registry import PLOT_REGISTRY


def test_spread_plot_groups_cover_fifteen_charts():
    assert SPREAD_PLOT_GROUPS["all"] == tuple(f"{i:02d}" for i in range(1, 16))
    assert plot_groups_for("spread") is SPREAD_PLOT_GROUPS


def test_spread_registry_has_all_run_plot_ids():
    for pid in SPREAD_PLOT_GROUPS["all"]:
        if pid == "14":
            continue  # compare-only via run_compare
        assert pid in PLOT_REGISTRY, f"missing plot {pid}"


def test_spread_adapter_name():
    assert SpreadAdapter().name == "spread"
