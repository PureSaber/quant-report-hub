"""Equity-specific charts for multifactor / sklearn outputs."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from quant_report_hub.context import PlotContext
from quant_report_hub.plots.style import NEU, apply_style, save_fig


def plot_16_ic_summary(ctx: PlotContext) -> Path | None:
    ic = ctx.extras.get("ic_summary")
    if ic is None or ic.empty:
        return None
    factor_col = "factor" if "factor" in ic.columns else ic.columns[0]
    value_col = "ic_mean" if "ic_mean" in ic.columns else ic.columns[-1]
    apply_style()
    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    ax.bar(ic[factor_col].astype(str), ic[value_col].astype(float), color=NEU)
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_title(f"{ctx.run_id} — IC 均值")
    ax.set_ylabel("IC")
    ax.tick_params(axis="x", rotation=30)
    out = ctx.out_dir / "16_ic_summary.png"
    return Path(save_fig(out, ctx.cfg.dpi))


def plot_17_synthesis_compare(ctx: PlotContext) -> Path | None:
    synth = ctx.extras.get("synthesis_summary")
    cap = ctx.extras.get("capital_curves")
    if cap is not None and not cap.empty and "date" in cap.columns:
        apply_style()
        _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
        for col in [c for c in cap.columns if c != "date"]:
            ax.plot(cap["date"], cap[col].astype(float), lw=1.2, label=col)
        ax.set_title(f"{ctx.run_id} — 合成方法资金曲线")
        ax.set_xlabel("日期")
        ax.set_ylabel("资金")
        ax.legend(fontsize=8)
        out = ctx.out_dir / "17_synthesis_curves.png"
        return Path(save_fig(out, ctx.cfg.dpi))
    if synth is None or synth.empty:
        return None
    apply_style()
    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    label_col = synth.columns[0]
    value_col = synth.columns[-1]
    ax.bar(synth[label_col].astype(str), synth[value_col].astype(float), color=NEU)
    ax.set_title(f"{ctx.run_id} — 合成对比")
    ax.tick_params(axis="x", rotation=20)
    out = ctx.out_dir / "17_synthesis_curves.png"
    return Path(save_fig(out, ctx.cfg.dpi))
