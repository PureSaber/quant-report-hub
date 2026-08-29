"""Equity-specific charts for multifactor / sklearn outputs."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from quant_report_hub.context import PlotContext
from quant_report_hub.plots.style import NEU, prepare_plot, save_ctx_plot


def plot_16_ic_summary(ctx: PlotContext) -> Path | None:
    ic = ctx.extras.get("ic_summary")
    if not prepare_plot(ic):
        return None
    factor_col = "factor" if "factor" in ic.columns else ic.columns[0]
    value_col = "ic_mean" if "ic_mean" in ic.columns else ic.columns[-1]
    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    ax.bar(ic[factor_col].astype(str), ic[value_col].astype(float), color=NEU)
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_title(f"{ctx.run_id} — IC 均值")
    ax.set_ylabel("IC")
    ax.tick_params(axis="x", rotation=30)
    return save_ctx_plot(ctx, "16_ic_summary.png")


def plot_17_synthesis_compare(ctx: PlotContext) -> Path | None:
    synth = ctx.extras.get("synthesis_summary")
    cap = ctx.extras.get("capital_curves")
    if cap is not None and not cap.empty and "date" in cap.columns:
        prepare_plot()
        _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
        for col in [c for c in cap.columns if c != "date"]:
            ax.plot(cap["date"], cap[col].astype(float), lw=1.2, label=col)
        ax.set_title(f"{ctx.run_id} — 合成方法资金曲线")
        ax.set_xlabel("日期")
        ax.set_ylabel("资金")
        ax.legend(fontsize=8)
        return save_ctx_plot(ctx, "17_synthesis_curves.png")
    if not prepare_plot(synth):
        return None
    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    label_col = synth.columns[0]
    value_col = synth.columns[-1]
    ax.bar(synth[label_col].astype(str), synth[value_col].astype(float), color=NEU)
    ax.set_title(f"{ctx.run_id} — 合成对比")
    ax.tick_params(axis="x", rotation=20)
    return save_ctx_plot(ctx, "17_synthesis_curves.png")


def plot_18_factor_ic_bar(ctx: PlotContext) -> Path | None:
    """Alias for IC bar chart used by factor smoke dashboards."""
    return plot_16_ic_summary(ctx)


def plot_19_quantile_spread(ctx: PlotContext) -> Path | None:
    cap = ctx.extras.get("capital_curves")
    if cap is None or cap.empty or "date" not in cap.columns:
        return None
    value_cols = [c for c in cap.columns if c != "date"]
    if len(value_cols) < 2:
        return None
    prepare_plot()
    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    top = cap[value_cols[0]].astype(float)
    bottom = cap[value_cols[-1]].astype(float)
    spread = top - bottom
    ax.plot(cap["date"], spread, color=NEU, lw=1.2)
    ax.set_title(f"{ctx.run_id} — quantile spread")
    ax.set_xlabel("日期")
    ax.set_ylabel("spread")
    return save_ctx_plot(ctx, "19_quantile_spread.png")
