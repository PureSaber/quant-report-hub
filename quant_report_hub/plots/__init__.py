"""Plot modules package."""
from __future__ import annotations

from quant_report_hub.plots.registry import PLOT_REGISTRY, run_compare, run_plots

__all__ = ["PLOT_REGISTRY", "run_plots", "run_compare"]
