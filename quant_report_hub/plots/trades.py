"""交易层图表：06, 09。"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from quant_report_hub.context import PlotContext
from quant_report_hub.plots.style import NEU, POS, apply_style, save_fig


def plot_06_roundtrip(ctx: PlotContext) -> Path | None:
    rt = ctx.roundtrips
    if rt.empty:
        return None
    apply_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    sns.histplot(rt["gross_pnl"], kde=True, ax=ax1, color=NEU, bins=30)
    ax1.set_title("Round-trip 净盈亏分布")
    ax1.set_xlabel("盈亏（元）")
    ax1.axvline(0, color="gray", ls="--")
    if rt["holding_minutes"].max() > 0:
        sns.histplot(rt["holding_minutes"] / 60, kde=True, ax=ax2, color=NEU, bins=30)
        ax2.set_title("持仓时长分布")
        ax2.set_xlabel("小时")
    else:
        ax2.text(0.5, 0.5, "持仓时长不可用", ha="center", va="center", transform=ax2.transAxes)
    out = ctx.out_dir / "06_roundtrip_pnl.png"
    return Path(save_fig(out, ctx.cfg.dpi))


def plot_09_signal_fill(ctx: PlotContext) -> Path | None:
    signals = ctx.signals
    trades = ctx.trades
    if signals.empty and trades.empty:
        return None
    apply_style()
    sig_daily = pd.Series(dtype=int)
    fill_daily = pd.Series(dtype=int)
    if not signals.empty:
        sig_daily = signals.groupby(signals["action_datetime"].dt.date).size()
        sig_daily.index = pd.to_datetime(sig_daily.index)
    if not trades.empty:
        fill_daily = trades.groupby(trades["datetime"].dt.date).size()
        fill_daily.index = pd.to_datetime(fill_daily.index)

    idx = sig_daily.index.union(fill_daily.index).sort_values()
    sdf = sig_daily.reindex(idx, fill_value=0)
    fdf = fill_daily.reindex(idx, fill_value=0)

    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(12, 6))
    ax1.plot(idx, sdf.values, label="信号数", color=NEU)
    ax1.plot(idx, fdf.values, label="成交笔数", color=POS)
    ax1.set_title(f"{ctx.run_id} — 信号 vs 成交")
    ax1.legend()
    ax1.set_ylabel("计数")
    conv = (fdf / sdf.replace(0, pd.NA)).fillna(0)
    monthly = conv.resample("ME").mean()
    ax2.bar(monthly.index, monthly.values * 100, width=20, color=NEU, alpha=0.8)
    ax2.set_title("月度成交转化率 (%)")
    ax2.set_ylabel("%")
    ax2.set_xlabel("日期")
    out = ctx.out_dir / "09_signal_vs_fill.png"
    return Path(save_fig(out, ctx.cfg.dpi))


__all__ = ["plot_06_roundtrip", "plot_09_signal_fill"]
