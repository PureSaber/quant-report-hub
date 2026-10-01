from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from quant_lab.contracts import write_standard_run

from quant_report_hub.attribution import (
    attribute_standard_run,
    brinson_fachler_attribution,
    factor_attribution,
    holdings_attribution,
)


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
        _positions(), _asset_returns(), costs=costs, portfolio_returns=observed, cost_unit="return"
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
        tags={"cost_unit": "currency"},
    )
    manifest = attribute_standard_run(tmp_path, _asset_returns())
    assert set(manifest.files) == {"holdings.csv", "summary.csv"}
    assert all(len(value) == 64 for value in manifest.files.values())
    assert (tmp_path / "attribution" / "manifest.json").is_file()


def _write_period_run(path: Path, *, scale: float = 1.0, tags=None):
    dates = ["2025-01-02", "2025-01-03"]
    positions = pd.DataFrame(
        {
            "date": dates,
            "strategy": ["alpha"] * 2,
            "symbol": ["A"] * 2,
            "quantity": [1.0] * 2,
            "market_value": [60.0, 63.0],
            "side": ["long"] * 2,
            "weight": [0.6] * 2,
            "return_weight": [0.5] * 2,
        }
    )
    returns = pd.DataFrame(
        {
            "date": dates,
            "strategy": ["alpha"] * 2,
            "gross_return": [0.1] * 2,
            "net_return": [0.05] * 2,
            "nav": [105 * scale, 110.25 * scale],
            "benchmark_return": [0.0] * 2,
        }
    )
    costs = pd.DataFrame(
        {
            "date": dates,
            "strategy": ["alpha"] * 2,
            "symbol": ["A"] * 2,
            "commission": [5 * scale, 5.25 * scale],
            "slippage": [0.0] * 2,
            "market_impact": [0.0] * 2,
            "borrow_cost": [0.0] * 2,
            "total_cost": [5 * scale, 5.25 * scale],
        }
    )
    write_standard_run(
        path,
        project="demo",
        run_id="period-run",
        strategy="alpha",
        frames={"positions": positions, "returns": returns, "costs": costs},
        metrics={},
        config={},
        code_version="test",
        tags=tags or {},
    )
    return pd.DataFrame({"date": dates, "symbol": ["A"] * 2, "return": [0.2] * 2})


@pytest.mark.parametrize("scale", [1.0, 1000.0])
def test_declared_period_weights_and_currency_costs_reconcile(tmp_path, scale):
    assets = _write_period_run(
        tmp_path,
        scale=scale,
        tags={
            "position_return_weight": "previous_decision_weight_for_return_attribution",
            "cost_unit": "currency",
        },
    )
    manifest = attribute_standard_run(tmp_path, assets)
    summary = pd.read_csv(tmp_path / "attribution" / "summary.csv")
    assert summary["gross_attributed_return"].tolist() == pytest.approx([0.1, 0.1])
    assert summary["cost_return"].tolist() == pytest.approx([0.05, 0.05])
    assert summary["net_residual"].abs().max() < 1e-12
    assert manifest.position_timing == "same_period_return_weight"
    assert manifest.cost_unit == "currency"


def test_period_weights_are_not_carried_into_a_missing_period():
    positions = _positions().assign(return_weight=0.5)
    detail, _ = holdings_attribution(positions, _asset_returns(), use_return_weights=True)
    assert detail["date"].unique().tolist() == [pd.Timestamp("2025-01-02")]
    assert detail["weight"].tolist() == [0.5]


def test_missing_declared_return_weights_are_rejected(tmp_path):
    assets = _write_period_run(tmp_path, tags={"cost_unit": "currency"})
    positions = _positions()
    with pytest.raises(ValueError, match="return_weight"):
        holdings_attribution(positions, assets, use_return_weights=True)
    with pytest.raises(ValueError, match="return_weight"):
        holdings_attribution(
            positions.assign(return_weight=float("nan")), assets, use_return_weights=True
        )


def test_legacy_costs_require_unit_and_cannot_override_declared_unit(tmp_path):
    assets = _write_period_run(tmp_path)
    with pytest.raises(ValueError, match="显式声明单位"):
        attribute_standard_run(tmp_path, assets)
    assert not (tmp_path / "attribution").exists()
    assert attribute_standard_run(tmp_path, assets, cost_unit="currency").cost_unit == "currency"
    tagged = tmp_path / "tagged"
    _write_period_run(tagged, tags={"cost_unit": "currency"})
    with pytest.raises(ValueError, match="声明冲突"):
        attribute_standard_run(tagged, assets, cost_unit="return")


def test_currency_costs_require_known_opening_capital():
    costs = pd.DataFrame({"date": ["2025-01-02"], "strategy": ["alpha"], "total_cost": [1.0]})
    observed = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "strategy": ["alpha"],
            "gross_return": [-0.9],
            "net_return": [-1.0],
            "nav": [0.0],
        }
    )
    with pytest.raises(ValueError, match="期初NAV"):
        holdings_attribution(_positions(), _asset_returns(), costs=costs, cost_unit="currency")
    with pytest.raises(ValueError, match="opening_nav"):
        holdings_attribution(
            _positions(),
            _asset_returns(),
            costs=costs,
            portfolio_returns=observed,
            cost_unit="currency",
        )
    _, summary = holdings_attribution(
        _positions(),
        _asset_returns(),
        costs=costs,
        portfolio_returns=observed.assign(opening_nav=10.0),
        cost_unit="currency",
    )
    assert summary.iloc[0]["cost_return"] == pytest.approx(0.1)


def test_brinson_uses_period_weights_without_shifting_benchmark():
    positions = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-02"],
            "strategy": ["alpha"] * 2,
            "symbol": ["A", "B"],
            "weight": [0.7, 0.3],
            "return_weight": [0.6, 0.4],
        }
    )
    benchmark = pd.DataFrame(
        {
            "date": ["2025-01-01"] * 2,
            "symbol": ["A", "B"],
            "weight": [0.5, 0.5],
        }
    )
    result = brinson_fachler_attribution(
        positions,
        benchmark,
        _asset_returns().iloc[:2],
        pd.DataFrame({"symbol": ["A", "B"], "group": ["growth", "value"]}),
        use_return_weights=True,
    )
    assert result["active_contribution"].sum() == pytest.approx(0.01)


def test_currency_costs_use_declared_return_capital_when_nav_is_an_index():
    costs = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-03"],
            "strategy": ["alpha"] * 2,
            "total_cost": [100.0, 200.0],
        }
    )
    observed = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-03"],
            "strategy": ["alpha"] * 2,
            "gross_return": [0.06, 0.10],
            "net_return": [0.05, 0.09],
            "nav": [1.05, 1.1445],
            "return_capital": [10000.0, 20000.0],
        }
    )
    _, summary = holdings_attribution(
        _positions(),
        _asset_returns(),
        costs=costs,
        portfolio_returns=observed,
        cost_unit="currency",
    )
    assert summary["cost_return"].tolist() == pytest.approx([0.01, 0.01])
    assert summary["net_residual"].abs().max() < 1e-12


def test_cli_can_attribute_legacy_cost_units(tmp_path):
    from quant_report_hub.cli import main

    assets = _write_period_run(tmp_path)
    asset_path = tmp_path / "asset_returns.csv"
    assets.to_csv(asset_path, index=False)
    assert (
        main(
            [
                "attribute",
                "--run-dir",
                str(tmp_path),
                "--asset-returns",
                str(asset_path),
                "--cost-unit",
                "currency",
            ]
        )
        == 0
    )
    summary = pd.read_csv(tmp_path / "attribution" / "summary.csv")
    assert summary["cost_return"].tolist() == pytest.approx([0.05])
