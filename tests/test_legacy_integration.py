from __future__ import annotations

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")

from quant_report_hub.adapters import get_adapter
from quant_report_hub.adapters.base import RunBundle, empty_bundle
from quant_report_hub.adapters.equity import EquityAdapter
from quant_report_hub.adapters.spread import SpreadAdapter
from quant_report_hub.config import VizConfig
from quant_report_hub.context import CompareContext, PlotContext
from quant_report_hub.loader import (
    load_portfolio,
    load_rolls,
    load_run,
    load_signals,
    load_summary,
    load_symbol_daily,
    load_trades,
)
from quant_report_hub.market import compute_zscore, load_spread_bars, spread_product
from quant_report_hub.metrics import (
    active_returns,
    drawdown_relative,
    monthly_returns,
    product_prefix,
    rolling_max_drawdown,
    rolling_sharpe,
    spread_cumulative_pnl,
    spread_nav,
    summarize_returns,
)
from quant_report_hub.plots.registry import run_compare, run_plots
from quant_report_hub.plots.style import prepare_plot


def _bundle(tmp_path, run_id: str = "demo") -> RunBundle:
    dates = pd.date_range("2025-01-01", periods=12, freq="D")
    portfolio = pd.DataFrame(
        {
            "date": dates,
            "daily_pnl": [1, -1, 2, 0, 1, -2, 2, 1, 0, 1, -1, 2],
            "daily_pnl_pct": [0.01, -0.01, 0.02, 0, 0.01, -0.02, 0.02, 0.01, 0, 0.01, -0.01, 0.02],
            "commission": [0.1] * 12,
            "num_trades": [2] * 12,
            "num_spreads": [2] * 12,
        }
    )
    symbols = []
    for spread, direction in (("A2505&B2501", 1), ("M2505&Y2501", -1)):
        for index, date in enumerate(dates):
            symbols.append(
                {
                    "date": date,
                    "spread": spread,
                    "daily_pnl": direction * (index % 3 + 1),
                    "daily_pnl_pct": direction * 0.01,
                    "commission": 0.1,
                }
            )
    trades = pd.DataFrame(
        {
            "instance_id": ["i1", "i1", "i2", "i2"],
            "spread": ["A2505&B2501", "A2505&B2501", "M2505&Y2501", "M2505&Y2501"],
            "datetime": [dates[0], dates[1], dates[2], dates[3]],
            "direction": ["LONG", "SHORT", "LONG", "SHORT"],
            "offset": ["OPEN", "CLOSE", "OPEN", "CLOSE"],
            "price": [100, 102, 99, 98],
            "volume": [1, 1, 1, 1],
            "commission": [0.1] * 4,
        }
    )
    signals = pd.DataFrame(
        {
            "symbol": ["A2505&B2501", "M2505&Y2501"],
            "offset": ["open", "open"],
            "action_datetime": [dates[0], dates[2]],
            "price": [100, 99],
            "bar_oi": [1000, 800],
        }
    )
    bundle = RunBundle(
        adapter="spread",
        run_id=run_id,
        run_dir=tmp_path / run_id,
        portfolio=portfolio,
        symbol=pd.DataFrame(symbols),
        trades=trades,
        signals=signals,
        rolls=pd.DataFrame({"tradingday": [dates[4], dates[8]]}),
        summary=pd.DataFrame({"value": [1]}),
        extras={
            "capital_curves": pd.DataFrame(
                {"date": dates, "q5": range(100, 112), "q1": range(99, 111)}
            ),
            "ic_summary": pd.DataFrame({"factor": ["value", "momentum"], "ic_mean": [0.02, -0.01]}),
            "synthesis_summary": pd.DataFrame({"method": ["a"], "score": [1.0]}),
        },
    )
    return bundle


def _market_fixture(tmp_path, spread: str) -> str:
    target = tmp_path / "market" / "2025" / "a" / "a"
    target.mkdir(parents=True)
    pd.DataFrame(
        {"datetime": pd.date_range("2025-01-01", periods=12, freq="D"), "close": range(100, 112)}
    ).to_csv(target / f"{spread}.csv", index=False)
    return str(tmp_path / "market")


def test_all_legacy_plots_and_compare_render(tmp_path):
    bundle = _bundle(tmp_path)
    root = _market_fixture(tmp_path, "A2505&B2501")
    cfg = VizConfig(
        output_root=str(tmp_path),
        run_id="demo",
        out_dir=str(tmp_path / "plots"),
        market_root=root,
        years=["2025"],
        strategy_params={"lookback": 3, "entry_z": 2, "exit_z": 0},
        top_n=2,
        rolling_windows=(3,),
    )
    ctx = PlotContext.from_bundle(cfg, bundle)
    outputs = run_plots(ctx, tuple(f"{item:02d}" for item in range(1, 20)))
    assert len(outputs) >= 15
    assert all(path.is_file() for path in outputs)
    comparison = CompareContext(
        cfg=cfg,
        runs=[ctx, PlotContext.from_bundle(cfg, _bundle(tmp_path, "other"))],
        out_dir=ctx.out_dir,
    )
    assert len(run_compare(comparison)) == 3


def test_loader_adapters_context_and_market_layout(tmp_path):
    root = tmp_path / "output"
    run = root / "r1"
    (run / "daily" / "portfolio").mkdir(parents=True)
    (run / "daily" / "symbol").mkdir(parents=True)
    (run / "trades").mkdir()
    (run / "signals").mkdir()
    (run / "rolls").mkdir()
    (run / "performance").mkdir()
    pd.DataFrame(
        {
            "日期": ["2025-01-01"],
            "日盈亏": [1],
            "日收益率": [0.01],
            "手续费": [0.1],
            "成交笔数": [1],
        }
    ).to_csv(run / "daily" / "portfolio" / "daily_pnl_portfolio_a.csv", index=False)
    pd.DataFrame(
        {
            "日期": ["2025-01-01"],
            "套利对": ["A2505&B2501"],
            "日盈亏": [1],
            "日收益率": [0.01],
            "手续费": [0.1],
        }
    ).to_csv(run / "daily" / "symbol" / "daily_pnl_a.csv", index=False)
    pd.DataFrame(
        {
            "实例ID": ["i"],
            "价差合约": ["A2505&B2501"],
            "成交时间": ["2025-01-01"],
            "交易日": ["2025-01-01"],
            "方向": ["LONG"],
            "开平": ["OPEN"],
            "成交价": [1],
            "成交量": [1],
            "手续费": [0.1],
        }
    ).to_csv(run / "trades" / "trades.csv", index=False)
    pd.DataFrame(
        {
            "symbol": ["A2505&B2501"],
            "action_datetime": ["2025-01-01"],
            "bar_datetime": ["2025-01-01"],
            "tradingday": ["2025-01-01"],
        }
    ).to_csv(run / "signals" / "signals_a.csv", index=False)
    pd.DataFrame({"tradingday": ["2025-01-01"]}).to_csv(
        run / "rolls" / "roll_events.csv", index=False
    )
    pd.DataFrame({"value": [1]}).to_csv(run / "performance" / "summary.csv")
    assert not load_portfolio(run).empty
    assert not load_symbol_daily(run).empty
    assert not load_trades(run).empty
    assert not load_signals(run).empty
    assert not load_rolls(run).empty
    assert not load_summary(run).empty
    assert load_run(root, "r1")["run_id"] == "r1"
    assert isinstance(SpreadAdapter().load(root, "r1"), RunBundle)
    with pytest.raises(TypeError, match="strategy"):
        PlotContext.from_run(VizConfig(str(root), "r1", str(tmp_path / "out")))
    with pytest.raises(FileNotFoundError):
        SpreadAdapter().load(root, "missing")
    with pytest.raises(ValueError, match="Unknown adapter"):
        get_adapter("unknown")
    assert empty_bundle("x", "r", run).portfolio.empty
    assert spread_product("A2505&B2501") == "a"
    assert load_spread_bars(tmp_path / "missing", "A2505&B2501", ["2025"]).empty
    bars_root = _market_fixture(tmp_path, "A2505&B2501")
    assert len(load_spread_bars(bars_root, "A2505&B2501", ["2025"])) == 12
    assert compute_zscore(pd.Series([1, 1, 1]), 2).isna().all()


def test_equity_adapter_and_metric_edge_cases(tmp_path):
    run = tmp_path / "equity"
    run.mkdir()
    pd.DataFrame({"date": ["2025-01-01", "2025-01-02"], "q5": [100, 110]}).to_csv(
        run / "capital_curves.csv", index=False
    )
    pd.DataFrame({"factor": ["value"], "ic_mean": [0.1]}).to_csv(
        run / "ic_summary.csv", index=False
    )
    pd.DataFrame({"method": ["a"], "score": [1]}).to_csv(
        run / "synthesis_comparison_summary.csv", index=False
    )
    pd.DataFrame({"factor": ["value"], "importance": [1]}).to_csv(
        run / "feature_importance.csv", index=False
    )
    assert not EquityAdapter().load(tmp_path, "equity").portfolio.empty
    assert EquityAdapter(strategy="missing").load(tmp_path, "equity").portfolio.empty
    assert EquityAdapter().load(tmp_path, "missing").portfolio.empty
    values = pd.Series([0.0, 0.01, -0.01])
    assert len(active_returns(values)) == 2
    assert drawdown_relative(pd.Series([0.0, 1.0, 0.5])).isna().iloc[0]
    assert summarize_returns(pd.Series(dtype=float))["calmar"] is None
    assert rolling_sharpe(values, 2).isna().iloc[0]
    assert rolling_max_drawdown(pd.Series([1.0, 0.5]), 2).iloc[-1] == -0.5
    assert spread_cumulative_pnl(pd.DataFrame()).empty
    assert spread_nav(pd.DataFrame()).empty
    assert product_prefix("123") == "12"
    assert len(monthly_returns(values, pd.Series(pd.date_range("2025-01-01", periods=3)))) == 1
    assert not prepare_plot(pd.DataFrame())
    assert prepare_plot()
