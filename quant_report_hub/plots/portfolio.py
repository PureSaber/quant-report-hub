"""组合层图表：01, 02, 04, 05, 12, 13。"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns

from quant_report_hub.context import PlotContext
from quant_report_hub.metrics import (
    active_returns,
    drawdown_additive,
    monthly_returns,
    portfolio_nav,
    rolling_max_drawdown,
    rolling_sharpe,
)
from quant_report_hub.plots.style import NEG, NEU, POS, prepare_plot, save_ctx_plot


def plot_01_nav_drawdown(ctx: PlotContext) -> Path | None:
    port = ctx.portfolio
    if not prepare_plot(port):
        return None
    nav = portfolio_nav(port)
    dd = drawdown_additive(nav)
    _fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=ctx.cfg.figsize_tall, gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(port["date"], nav, color=NEU, lw=1.5)
    ax1.set_title(f"{ctx.run_id} — 组合净值")
    ax1.set_ylabel("净值")
    ax1.axhline(1.0, color="gray", ls="--", lw=0.8)
    ax2.fill_between(port["date"], dd, 0, where=dd <= 0, color=NEG, alpha=0.4)
    ax2.plot(port["date"], dd, color=NEG, lw=1)
    ax2.set_title("加性回撤")
    ax2.set_ylabel("回撤")
    ax2.set_xlabel("日期")
    return save_ctx_plot(ctx, "01_nav_drawdown.png")


def plot_02_daily_pnl_dist(ctx: PlotContext) -> Path | None:
    port = ctx.portfolio
    if not prepare_plot(port):
        return None
    _fig, (ax1, ax2) = plt.subplots(1, 2, figsize=ctx.cfg.figsize_wide)
    colors = [POS if v >= 0 else NEG for v in port["daily_pnl"]]
    ax1.bar(port["date"], port["daily_pnl"], color=colors, width=1.0)
    ax1.set_title("日盈亏")
    ax1.set_xlabel("日期")
    ax1.set_ylabel("日盈亏（元）")
    active = active_returns(port["daily_pnl_pct"])
    if not active.empty:
        sns.histplot(active * 100, kde=True, ax=ax2, color=NEU, bins=30)
        ax2.set_title("活跃日收益率分布")
        ax2.set_xlabel("日收益率 (%)")
    else:
        ax2.text(0.5, 0.5, "无活跃日", ha="center", va="center", transform=ax2.transAxes)
    return save_ctx_plot(ctx, "02_daily_pnl.png")


def plot_04_commission_vs_pnl(ctx: PlotContext) -> Path | None:
    port = ctx.portfolio
    if not prepare_plot(port):
        return None
    gross_pnl = port["daily_pnl"] + port["commission"]
    cum_net = port["daily_pnl"].cumsum()
    cum_gross = gross_pnl.cumsum()
    cum_comm = port["commission"].cumsum()
    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    ax.plot(port["date"], cum_gross, label="累计毛盈亏", color=POS, lw=1.5)
    ax.plot(port["date"], cum_net, label="累计净盈亏", color=NEU, lw=1.5)
    ax.plot(port["date"], cum_comm, label="累计手续费", color=NEG, lw=1.2, ls="--")
    ax.set_title(f"{ctx.run_id} — 手续费 vs 盈亏")
    ax.set_xlabel("日期")
    ax.set_ylabel("累计（元）")
    ax.legend()
    return save_ctx_plot(ctx, "04_commission_vs_pnl.png")


def plot_05_activity(ctx: PlotContext) -> Path | None:
    port = ctx.portfolio
    if not prepare_plot(port):
        return None
    sym = ctx.symbol
    active_spreads = None
    if not sym.empty:
        active = sym[sym["daily_pnl"] != 0].groupby("date")["spread"].nunique()
        active_spreads = active.reindex(port["date"]).fillna(0)
    _fig, ax1 = plt.subplots(figsize=ctx.cfg.figsize_wide)
    ax1.bar(port["date"], port["num_trades"], color=NEU, alpha=0.7, width=1.0, label="成交笔数")
    ax1.set_ylabel("成交笔数")
    ax1.set_title(f"{ctx.run_id} — 交易活跃度")
    if "num_spreads" in port.columns:
        ax2 = ax1.twinx()
        ax2.plot(port["date"], port["num_spreads"], color=NEG, lw=1.2, label="universe 套利对数")
        if active_spreads is not None:
            ax2.plot(active_spreads.index, active_spreads.values, color=POS, lw=1.0, ls="--", label="当日活跃套利对")
        ax2.set_ylabel("套利对数")
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    ax1.set_xlabel("日期")
    return save_ctx_plot(ctx, "05_activity.png")


def plot_12_monthly(ctx: PlotContext) -> Path | None:
    port = ctx.portfolio
    if not prepare_plot(port):
        return None
    monthly = monthly_returns(port["daily_pnl_pct"], port["date"])
    monthly["label"] = monthly["year"].astype(str) + "-" + monthly["month"].astype(str).str.zfill(2)
    annual = port.groupby(port["date"].dt.year)["daily_pnl_pct"].sum().reset_index()
    annual.columns = ["year", "ret"]
    _fig, axes = plt.subplots(1, 3, figsize=(16, 4))
    axes[0].bar(monthly["label"], monthly["ret"] * 100, color=[POS if v >= 0 else NEG for v in monthly["ret"]])
    axes[0].set_title("月度收益率")
    axes[0].tick_params(axis="x", rotation=90)
    axes[0].set_ylabel("%")
    if len(monthly) >= 2:
        pivot = monthly.pivot(index="year", columns="month", values="ret")
        sns.heatmap(pivot * 100, annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=axes[1])
        axes[1].set_title("月收益热力图 (%)")
    else:
        axes[1].text(0.5, 0.5, "数据不足", ha="center", va="center", transform=axes[1].transAxes)
    axes[2].bar(annual["year"].astype(str), annual["ret"] * 100, color=[POS if v >= 0 else NEG for v in annual["ret"]])
    axes[2].set_title("年度收益率")
    axes[2].set_ylabel("%")
    return save_ctx_plot(ctx, "12_monthly_returns.png")


def plot_13_rolling(ctx: PlotContext) -> Path | None:
    port = ctx.portfolio
    if not prepare_plot(port):
        return None
    nav = portfolio_nav(port)
    fig, axes = plt.subplots(len(ctx.cfg.rolling_windows), 1, sharex=True, figsize=ctx.cfg.figsize_tall)
    if len(ctx.cfg.rolling_windows) == 1:
        axes = [axes]
    for ax, w in zip(axes, ctx.cfg.rolling_windows):
        rs = rolling_sharpe(port["daily_pnl_pct"], w)
        rm = rolling_max_drawdown(nav, w)
        ax.plot(port["date"], rs, label=f"滚动 Sharpe ({w}日)", color=NEU)
        ax2 = ax.twinx()
        ax2.plot(port["date"], rm * 100, label=f"滚动最大回撤 ({w}日)", color=NEG, alpha=0.8)
        ax.set_ylabel("Sharpe")
        ax2.set_ylabel("回撤 (%)")
        ax.set_title(f"窗口 {w} 日")
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    axes[-1].set_xlabel("日期")
    fig.suptitle(f"{ctx.run_id} — 滚动指标", y=1.02)
    return save_ctx_plot(ctx, "13_rolling_metrics.png")


__all__ = [
    "plot_01_nav_drawdown",
    "plot_02_daily_pnl_dist",
    "plot_04_commission_vs_pnl",
    "plot_05_activity",
    "plot_12_monthly",
    "plot_13_rolling",
]
