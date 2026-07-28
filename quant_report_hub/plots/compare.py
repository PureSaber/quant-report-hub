"""多 run 对比：14。"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from quant_report_hub.context import CompareContext
from quant_report_hub.metrics import net_value_from_pct, summarize_returns
from quant_report_hub.plots.style import apply_style, save_fig


def plot_14_multi_run(ctx: CompareContext) -> list[Path]:
    if len(ctx.runs) < 2:
        return []
    apply_style()
    outputs: list[Path] = []

    fig, ax = plt.subplots(figsize=ctx.cfg.figsize_wide)
    metrics_rows = []
    for run in ctx.runs:
        port = run.portfolio
        if port.empty:
            continue
        nav = port["net_value"] if "net_value" in port.columns else net_value_from_pct(port["daily_pnl_pct"])
        ax.plot(port["date"], nav, lw=1.5, label=run.run_id)
        m = summarize_returns(port["daily_pnl_pct"])
        comm_ratio = float(port["commission"].sum() / max(abs(port["daily_pnl"].sum() + port["commission"].sum()), 1))
        metrics_rows.append({
            "run_id": run.run_id,
            "sharpe": m["sharpe"],
            "max_dd": abs(m["max_drawdown"] or 0),
            "calmar": m["calmar"] or 0,
            "win_rate": m["win_rate"],
            "comm_ratio": comm_ratio,
            "total_return": m["total_return"],
        })
    ax.set_title("多 run 净值对比")
    ax.legend()
    ax.set_xlabel("日期")
    ax.set_ylabel("净值")
    p1 = ctx.out_dir / "14_multi_nav.png"
    outputs.append(Path(save_fig(p1, ctx.cfg.dpi)))

    if len(metrics_rows) >= 2:
        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw={"projection": "polar"})
        labels = ["Sharpe", "Calmar", "胜率", "累计收益", "1-手续费占比"]
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        angles += angles[:1]
        for row in metrics_rows:
            vals = [
                max(0, min(row["sharpe"] / 2, 1)),
                max(0, min(row["calmar"] / 3, 1)),
                row["win_rate"],
                max(0, min(row["total_return"] * 10, 1)),
                max(0, 1 - row["comm_ratio"]),
            ]
            vals += vals[:1]
            ax.plot(angles, vals, lw=1.5, label=row["run_id"])
            ax.fill(angles, vals, alpha=0.1)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels)
        ax.set_title("指标雷达（归一化）")
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
        p2 = ctx.out_dir / "14_metrics_radar.png"
        outputs.append(Path(save_fig(p2, ctx.cfg.dpi)))

        fig, ax = plt.subplots(figsize=(6, 5))
        for row in metrics_rows:
            ax.scatter(abs(row["max_dd"]) * 100, row["total_return"] * 100, s=80, label=row["run_id"])
            ax.annotate(row["run_id"], (abs(row["max_dd"]) * 100, row["total_return"] * 100), fontsize=8)
        ax.set_xlabel("最大回撤 (%)")
        ax.set_ylabel("累计收益率 (%)")
        ax.set_title("收益 vs 回撤")
        ax.legend()
        p3 = ctx.out_dir / "14_return_vs_drawdown.png"
        outputs.append(Path(save_fig(p3, ctx.cfg.dpi)))
    return outputs


__all__ = ["plot_14_multi_run"]
