"""Measured multi-run comparison; legacy run charts remain read-only."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from quant_measurement import compare_measurements, validate_observations

from quant_report_hub.context import CompareContext
from quant_report_hub.plots.style import prepare_plot, save_ctx_plot


def plot_14_multi_run(ctx: CompareContext) -> list[Path]:
    decision = compare_measurements([run.measurement for run in ctx.runs])
    if not decision["comparable"]:
        raise ValueError("Economic comparison unavailable: " + json.dumps(decision["reasons"]))
    basis = ctx.runs[0].measurement["basis"]
    if basis["return_unit"] != "decimal" or basis["return_basis"] != "net_simple_time_weighted":
        raise ValueError("Comparison plot supports decimal net_simple_time_weighted only")
    curves, summaries = [], []
    for run in ctx.runs:
        if run.adapter != "standard" or "net_return" not in run.portfolio:
            raise ValueError("Measured plots require the native standard adapter")
        port = run.portfolio
        grid = [basis["period_start"], *[t.isoformat().replace("+00:00", "Z") for t in port.date]]
        validate_observations(run.measurement, grid)
        rates = port.net_return.to_numpy(dtype=float)
        if not np.isfinite(rates).all() or (rates < -1).any():
            raise ValueError("Finite simple net returns no less than -1 required")
        nav = np.r_[1.0, np.cumprod(1 + rates)]
        dd = nav / np.maximum.accumulate(nav) - 1
        curves.append((run.run_id, pd.to_datetime(grid, utc=True), nav, dd))
        summaries.append(
            {
                "run_id": run.run_id,
                "total_return": float(nav[-1] - 1),
                "max_drawdown": float(dd.min()),
                "annualized_metrics": None,
            }
        )
    prepare_plot()
    outputs = []
    for column, name, title in (
        (2, "14_multi_nav.png", "Measured net wealth"),
        (3, "14_drawdown.png", "Relative drawdown including opening capital"),
    ):
        _, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
        for curve in curves:
            ax.plot(curve[1], curve[column], label=curve[0])
        ax.set_title(title + " — " + ctx.runs[0].measurement["evidence_kind"])
        ax.legend()
        outputs.append(save_ctx_plot(ctx, name))
    report = ctx.out_dir / "measurement-comparison.json"
    report.write_text(
        json.dumps(
            {
                "comparison": decision,
                "measurement": [r.measurement for r in ctx.runs],
                "metrics": summaries,
                "limitations": [
                    "Declared compatibility is not market validity or investment ranking.",
                    "Annualized metrics are not computed by this plot.",
                ],
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    outputs.append(report)
    return outputs


__all__ = ["plot_14_multi_run"]
