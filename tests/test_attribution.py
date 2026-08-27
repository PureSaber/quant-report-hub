from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quant_report_hub.attribution import (
    attribute_standard_run,
    brinson_fachler_attribution,
    factor_attribution,
    holdings_attribution,
)
from quant_lab.contracts import write_standard_run


def _positions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-01", "2025-01-02"],
            "strategy": ["alpha", "alpha", "alpha"],
            "symbol": ["A", "B", "B"],
            "weight": [0.6, 0.4, 1.0],
        }
    )


def _asset_returns() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-02", "2025-01-03", "2025-01-03"],
            "symbol": ["A", "B", "A", "B"],
            "return": [0.10, 0.00, -0.50, 0.10],
        }
    )


def test_holdings_attribution_uses_complete_prior_snapshot_and_reconciles_costs():
    costs = pd.DataFrame({"date": ["2025-01-02"], "strategy": ["alpha"], "total_cost": [0.01]})
    observed = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-03"],
            "strategy": ["alpha", "alpha"],
            "gross_return": [0.06, 0.10],
            "net_return": [0.05, 0.10],
        }
    )
    detail, summary = holdings_attribution(
        _positions(), _asset_returns(), costs=costs, portfolio_returns=observed
    )
    by_date = summary.set_index("date")
    assert by_date.loc[pd.Timestamp("2025-01-02"), "gross_attributed_return"] == pytest.approx(0.06)
    assert by_date.loc[pd.Timestamp("2025-01-02"), "net_attributed_return"] == pytest.approx(0.05)
    assert by_date.loc[pd.Timestamp("2025-01-03"), "gross_attributed_return"] == pytest.approx(0.10)
    jan3 = detail.loc[detail["date"].eq(pd.Timestamp("2025-01-03"))]
    assert jan3["symbol"].tolist() == ["B"]
    assert by_date["net_residual"].abs().max() == pytest.approx(0.0)


def test_factor_attribution_separates_specific_return():
    exposures = pd.DataFrame(
        {
            "date": ["2025-01-01"],
            "strategy": ["alpha"],
            "exposure_type": ["factor"],
            "name": ["market"],
            "value": [0.5],
        }
    )
    factor_returns = pd.DataFrame({"date": ["2025-01-02"], "name": ["market"], "return": [0.02]})
    portfolio_returns = pd.DataFrame(
        {"date": ["2025-01-02"], "strategy": ["alpha"], "gross_return": [0.03]}
    )
    detail, summary = factor_attribution(
        exposures, factor_returns, portfolio_returns=portfolio_returns
    )
    assert detail.loc[0, "factor_contribution"] == pytest.approx(0.01)
    assert summary.loc[0, "specific_return"] == pytest.approx(0.02)


def test_brinson_components_reconcile_active_return():
    benchmark = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-01"],
            "symbol": ["A", "B"],
            "weight": [0.5, 0.5],
        }
    )
    classes = pd.DataFrame({"symbol": ["A", "B"], "group": ["growth", "value"]})
    result = brinson_fachler_attribution(
        _positions().loc[lambda x: x["date"].eq("2025-01-01")],
        benchmark,
        _asset_returns().loc[lambda x: x["date"].eq("2025-01-02")],
        classes,
    )
    actual_active = 0.06 - 0.05
    assert result["active_contribution"].sum() == pytest.approx(actual_active)


def test_attribute_standard_run_writes_hashed_bundle(tmp_path: Path):
    positions = _positions().assign(quantity=0, market_value=0, side="long")
    returns = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-03"],
            "strategy": ["alpha", "alpha"],
            "gross_return": [0.06, 0.10],
            "net_return": [0.05, 0.10],
            "nav": [1.05, 1.155],
            "benchmark_return": [0.0, 0.0],
        }
    )
    costs = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "strategy": ["alpha"],
            "symbol": ["__portfolio__"],
            "commission": [0.01],
            "slippage": [0.0],
            "market_impact": [0.0],
            "borrow_cost": [0.0],
            "total_cost": [0.01],
        }
    )
    write_standard_run(
        tmp_path,
        project="demo",
        run_id="demo-run",
        strategy="alpha",
        frames={"positions": positions, "returns": returns, "costs": costs},
        metrics={},
        config={},
        code_version="test",
    )
    manifest = attribute_standard_run(tmp_path, _asset_returns())
    assert set(manifest.files) == {"holdings.csv", "summary.csv"}
    assert all(len(value) == 64 for value in manifest.files.values())
    assert (tmp_path / "attribution" / "manifest.json").is_file()
