"""Equity research output adapter (a-share-multifactor / sklearn-stock-trend)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_report_hub.adapters.base import RunBundle, empty_bundle


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _capital_curve_to_portfolio(df: pd.DataFrame, strategy_col: str, initial_capital: float) -> pd.DataFrame:
    if df.empty or "date" not in df.columns or strategy_col not in df.columns:
        return pd.DataFrame()
    out = df[["date", strategy_col]].copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date")
    values = out[strategy_col].astype(float)
    out["net_value"] = values / float(initial_capital) if initial_capital else values
    out["daily_pnl"] = values.diff().fillna(0.0)
    out["daily_pnl_pct"] = out["net_value"].diff().fillna(0.0)
    out["commission"] = 0.0
    out["strategy"] = strategy_col
    return out


class EquityAdapter:
    name = "equity"

    def __init__(self, strategy: str = "", initial_capital: float = 10000.0) -> None:
        self.strategy = strategy
        self.initial_capital = initial_capital

    def load(self, output_root: str | Path, run_id: str) -> RunBundle:
        root = Path(output_root)
        run_path = root / run_id if (root / run_id).is_dir() else root
        if not run_path.is_dir():
            raise FileNotFoundError(f"run 目录不存在: {run_path}")

        cap_path = run_path / "capital_curves.csv"
        cap = _read_csv(cap_path)
        strategy = self.strategy
        if not strategy and not cap.empty:
            cols = [c for c in cap.columns if c != "date"]
            strategy = cols[0] if cols else ""
        portfolio = _capital_curve_to_portfolio(cap, strategy, self.initial_capital)

        extras = {
            "capital_curves": cap,
            "ic_summary": _read_csv(run_path / "ic_summary.csv"),
            "synthesis_summary": _read_csv(run_path / "synthesis_comparison_summary.csv"),
            "feature_importance": _read_csv(run_path / "feature_importance.csv"),
        }
        bundle = empty_bundle(self.name, run_path.name, run_path)
        bundle.portfolio = portfolio
        bundle.extras = extras
        return bundle


def get_equity_adapter(strategy: str = "", initial_capital: float = 10000.0) -> EquityAdapter:
    return EquityAdapter(strategy=strategy, initial_capital=initial_capital)
