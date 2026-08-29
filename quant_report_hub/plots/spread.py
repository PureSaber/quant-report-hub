"""套利对 universe 图表：03, 07, 15。"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from quant_report_hub.context import PlotContext
from quant_report_hub.metrics import monthly_returns, portfolio_nav, product_prefix, spread_nav
from quant_report_hub.plots.style import NEG, NEU, POS, prepare_plot, save_ctx_plot


def _top_bottom_spreads(pnl: pd.Series, n: int) -> list[str]:
    if pnl.empty:
        return []
    top = list(pnl.head(n).index)
    bottom = list(pnl.tail(n).index)
    return list(dict.fromkeys(top + bottom))


def plot_03_spread_nav(ctx: PlotContext) -> list[Path]:
    sym = ctx.symbol
    if not prepare_plot(sym):
        return []
    n = ctx.cfg.top_n
    pnl = ctx.spread_pnl
    picks = _top_bottom_spreads(pnl, n)
    nav_df = spread_nav(sym)
    port_nav = ctx.portfolio
    outputs: list[Path] = []

    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_tall)
    for spread in picks:
        g = nav_df[nav_df["spread"] == spread]
        if g.empty:
            continue
        ax.plot(g["date"], g["nav"], lw=1.0, label=spread, alpha=0.85)
    if not port_nav.empty:
        ax.plot(
            port_nav["date"], portfolio_nav(port_nav), color="black", lw=2.0, ls="--", label="组合"
        )
    ax.set_title(f"{ctx.run_id} — Top/Bottom {n} 套利对净值")
    ax.legend(fontsize=7, ncol=2, loc="upper left")
    ax.set_xlabel("日期")
    ax.set_ylabel("净值")
    outputs.append(save_ctx_plot(ctx, "03_spread_nav_compare.png"))

    # 月收益热力图：选累计 PnL 绝对值最大的 top 20 活跃 pair
    active_pnl = pnl[pnl != 0].abs().sort_values(ascending=False).head(20).index.tolist()
    if active_pnl:
        rows = []
        for spread in active_pnl:
            g = sym[sym["spread"] == spread]
            if g.empty:
                continue
            m = monthly_returns(g["daily_pnl_pct"], g["date"])
            m["spread"] = spread
            rows.append(m)
        if rows:
            mdf = pd.concat(rows, ignore_index=True)
            mdf["ym"] = mdf["year"].astype(str) + "-" + mdf["month"].astype(str).str.zfill(2)
            pivot = mdf.pivot(index="spread", columns="ym", values="ret").fillna(0)
            _fig, ax = plt.subplots(
                figsize=(max(10, pivot.shape[1] * 0.4), max(6, pivot.shape[0] * 0.3))
            )
            sns.heatmap(pivot * 100, cmap="RdYlGn", center=0, ax=ax, linewidths=0.2)
            ax.set_title("Top 活跃套利对 — 月收益率 (%)")
            outputs.append(save_ctx_plot(ctx, "03_spread_monthly_heatmap.png"))
    return outputs


def plot_07_spread_rank(ctx: PlotContext) -> Path | None:
    pnl = ctx.spread_pnl
    sym = ctx.symbol
    trades = ctx.trades
    if not prepare_plot(pnl):
        return None
    top = pnl.head(30)
    trade_cnt = trades.groupby("spread").size() if not trades.empty else pd.Series(dtype=int)
    comm = sym.groupby("spread")["commission"].sum() if not sym.empty else pd.Series(dtype=float)

    _fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    colors = [POS if v >= 0 else NEG for v in top.values]
    ax1.barh(top.index[::-1], top.values[::-1], color=colors[::-1])
    ax1.set_title("套利对累计净盈亏 Top 30")
    ax1.set_xlabel("累计日盈亏（元）")

    bubble = pd.DataFrame({"spread": top.index, "pnl": top.values})
    bubble["trades"] = bubble["spread"].map(trade_cnt).fillna(0)
    bubble["commission"] = bubble["spread"].map(comm).fillna(0)
    sizes = np.clip(bubble["commission"] / max(bubble["commission"].max(), 1) * 400, 20, 400)
    ax2.scatter(bubble["trades"], bubble["pnl"], s=sizes, alpha=0.6, c=bubble["pnl"], cmap="RdYlGn")
    for _, row in bubble.iterrows():
        ax2.annotate(row["spread"], (row["trades"], row["pnl"]), fontsize=6, alpha=0.7)
    ax2.set_xlabel("成交笔数")
    ax2.set_ylabel("累计净盈亏")
    ax2.set_title("交易次数 vs 收益（气泡=手续费）")
    ax2.axhline(0, color="gray", lw=0.8)
    return save_ctx_plot(ctx, "07_spread_contribution.png")


def plot_15_correlation(ctx: PlotContext) -> list[Path]:
    sym = ctx.symbol
    if not prepare_plot(sym):
        return []
    outputs: list[Path] = []
    active = sym[sym["daily_pnl"] != 0].groupby("spread")["daily_pnl"].sum()
    picks = active.abs().sort_values(ascending=False).head(50).index.tolist()
    if len(picks) < 2:
        return outputs

    wide = (
        sym[sym["spread"].isin(picks)]
        .pivot_table(
            index="date",
            columns="spread",
            values="daily_pnl_pct",
            aggfunc="sum",
        )
        .fillna(0)
    )
    corr = wide.corr()
    _fig, ax = plt.subplots(figsize=(12, 10))
    sns.heatmap(corr, cmap="coolwarm", center=0, ax=ax, xticklabels=True, yticklabels=True)
    ax.set_title(f"{ctx.run_id} — Top50 活跃套利对日收益相关性")
    outputs.append(save_ctx_plot(ctx, "15_correlation_heatmap.png"))

    active_cnt = (wide != 0).sum(axis=1)
    _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    ax.plot(active_cnt.index, active_cnt.values, color=NEU)
    ax.set_title("每日非零收益套利对数量")
    ax.set_xlabel("日期")
    ax.set_ylabel("数量")
    outputs.append(save_ctx_plot(ctx, "15_active_spread_count.png"))

    sym2 = sym.copy()
    sym2["sector"] = sym2["spread"].map(product_prefix)
    sector_pnl = sym2.groupby("sector")["daily_pnl"].sum().sort_values(ascending=False)
    if not sector_pnl.empty:
        sector_daily = sym2.groupby(["date", "sector"])["daily_pnl"].sum().reset_index()
        _fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
        sns.boxplot(data=sector_daily, x="sector", y="daily_pnl", ax=ax, showfliers=False)
        ax.set_title("品种板块日盈亏分布")
        ax.tick_params(axis="x", rotation=45)
        outputs.append(save_ctx_plot(ctx, "15_sector_boxplot.png"))
    return outputs


__all__ = ["plot_03_spread_nav", "plot_07_spread_rank", "plot_15_correlation"]
