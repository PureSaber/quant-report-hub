"""诊断图表：08, 10, 11。"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from quant_report_hub.context import PlotContext
from quant_report_hub.market import compute_zscore, load_spread_bars
from quant_report_hub.metrics import portfolio_nav
from quant_report_hub.plots.style import NEG, NEU, POS, prepare_plot, save_ctx_plot


def _diagnostic_spreads(ctx: PlotContext, n: int = 5) -> list[str]:
    pnl = ctx.spread_pnl
    if pnl.empty:
        return []
    top = list(pnl.head(n).index)
    bottom = list(pnl.tail(n).index)
    zero = [s for s in pnl.index if pnl[s] == 0][:n]
    return list(dict.fromkeys(top + bottom + zero))


def plot_08_zscore(ctx: PlotContext) -> list[Path]:
    if not ctx.cfg.market_root or not ctx.cfg.years:
        return []
    spreads = _diagnostic_spreads(ctx)
    if not spreads:
        return []
    lookback = int(ctx.cfg.strategy_params.get("lookback", 300))
    entry_z = float(ctx.cfg.strategy_params.get("entry_z", 3.5))
    exit_z = float(ctx.cfg.strategy_params.get("exit_z", 0.0))
    sub = ctx.out_dir / "08_diagnostics"
    sub.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    for spread in spreads:
        bars = load_spread_bars(ctx.cfg.market_root, spread, ctx.cfg.years)
        if bars.empty:
            continue
        prepare_plot()
        z = compute_zscore(bars["close"], lookback)
        _fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(12, 7), gridspec_kw={"height_ratios": [2, 1]})
        ax1.plot(bars["datetime"], bars["close"], color=NEU, lw=1)
        ax1.set_title(f"{spread} — 价差与 z-score")
        ax1.set_ylabel("comb 收盘价")

        sig = ctx.signals[ctx.signals["symbol"] == spread] if not ctx.signals.empty else pd.DataFrame()
        tr = ctx.trades[ctx.trades["spread"] == spread] if not ctx.trades.empty else pd.DataFrame()
        if not sig.empty:
            entries = sig[sig["offset"] == "open"]
            ax1.scatter(entries["action_datetime"], entries["price"], c=POS, s=20, label="entry", zorder=3)
        if not tr.empty:
            opens = tr[tr["offset"].str.upper() == "OPEN"]
            closes = tr[tr["offset"].str.upper() == "CLOSE"]
            ax1.scatter(opens["datetime"], opens["price"], marker="^", c=POS, s=40, label="fill open", zorder=4)
            ax1.scatter(closes["datetime"], closes["price"], marker="v", c=NEG, s=40, label="fill close", zorder=4)
        ax1.legend(fontsize=8)

        ax2.plot(bars["datetime"], z, color=NEU, lw=0.8)
        ax2.axhline(entry_z, color=NEG, ls="--", lw=0.8)
        ax2.axhline(-entry_z, color=NEG, ls="--", lw=0.8)
        ax2.axhline(exit_z, color="gray", ls=":", lw=0.8)
        ax2.axhline(-exit_z, color="gray", ls=":", lw=0.8)
        ax2.set_ylabel("z-score")
        ax2.set_xlabel("时间")
        safe = spread.replace("&", "_").replace("/", "_")
        outputs.append(save_ctx_plot(ctx, sub / f"08_zscore_{safe}.png"))
    return outputs


def plot_10_oi_filter(ctx: PlotContext) -> Path | None:
    signals = ctx.signals
    trades = ctx.trades
    if not prepare_plot(signals):
        return None
    entries = signals[signals["offset"] == "open"].copy()
    _fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    if "bar_oi" in entries.columns:
        ax1.scatter(entries["bar_oi"], entries["price"], alpha=0.5, s=15, c=NEU)
        ax1.set_xlabel("bar OI")
        ax1.set_ylabel("信号价格")
        ax1.set_title("开仓信号 OI 分布")
    else:
        ax1.text(0.5, 0.5, "无 OI 字段", ha="center", va="center", transform=ax1.transAxes)

    if not trades.empty:
        entry_days = set(entries["action_datetime"].dt.date)
        fill_days = set(trades["datetime"].dt.date)
        sig_no_fill = len(entry_days - fill_days)
        both = len(entry_days & fill_days)
        ax2.bar(["有成交日", "仅信号无成交日"], [both, sig_no_fill], color=[POS, NEG])
        ax2.set_title("信号日 vs 成交日")
    else:
        ax2.bar(["信号日"], [entries["action_datetime"].dt.date.nunique()], color=NEU)
        ax2.set_title("仅信号、无成交")
    return save_ctx_plot(ctx, "10_oi_filter.png")


def plot_11_roll_events(ctx: PlotContext) -> Path | None:
    rolls = ctx.rolls
    port = ctx.portfolio
    if not prepare_plot(port, rolls):
        return None
    nav = portfolio_nav(port)
    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    ax.plot(port["date"], nav, color=NEU, lw=1.5)
    roll_dates = pd.to_datetime(rolls["tradingday"]).dropna().unique()
    for d in roll_dates:
        ax.axvline(pd.Timestamp(d), color=NEG, alpha=0.25, lw=0.8)
    ax.set_title(f"{ctx.run_id} — 换月事件 ({len(roll_dates)} 次)")
    ax.set_xlabel("日期")
    ax.set_ylabel("组合净值")
    return save_ctx_plot(ctx, "11_roll_events.png")


__all__ = ["plot_08_zscore", "plot_10_oi_filter", "plot_11_roll_events"]
