from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from quant_lab.contracts import write_standard_run
from quant_lab.contracts_v2 import (
    ARTIFACT_SCHEMAS_V2,
    BACKTEST_LEDGER_PROFILE,
    write_standard_run_v2,
)

from quant_report_hub import attribution as v2
from quant_report_hub.attribution import V2AttributionError, reconcile_standard_run_v2
from quant_report_hub.cli import main

T0 = pd.Timestamp("2025-01-02T00:00:00Z")
T1 = pd.Timestamp("2025-01-03T00:00:00Z")
BASE = "USD"


def _frame(name: str, rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=ARTIFACT_SCHEMAS_V2[name])


def _source_row(component: str, units: int, *, currency: str = BASE, base_units: int | None = None):
    return {
        "event_time": T1,
        "account_id": "acct-1",
        "strategy_id": "alpha",
        "instrument_id": "instrument-1",
        "component": component,
        "amount_units": units,
        "amount_scale": 0,
        "currency": currency,
        "base_amount_units": units if base_units is None else base_units,
        "base_amount_scale": 0,
        "base_currency": BASE,
    }


def _cost_rows(specs: list[tuple[str, int, str | None]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    costs: list[dict] = []
    ledger: list[dict] = []
    for index, (component, amount, fill_id) in enumerate(specs, start=1):
        cost_id = f"cost-{index}"
        costs.append(
            {
                "event_time": T1,
                "cost_id": cost_id,
                "account_id": "acct-1",
                "strategy_id": "alpha",
                "instrument_id": "instrument-1",
                "fill_id": fill_id,
                "cost_type": component,
                "amount_units": amount,
                "amount_scale": 0,
                "currency": BASE,
            }
        )
        event_type = "funding" if component == "funding" else "fee"
        cash_amount = -amount
        ledger.extend(
            [
                {
                    "event_time": T1,
                    "transaction_id": f"txn-{index}",
                    "idempotency_key": f"key-{index}",
                    "event_type": event_type,
                    "reference_id": cost_id,
                    "posting_index": 0,
                    "ledger_account": "assets:cash",
                    "account_id": "acct-1",
                    "currency": BASE,
                    "amount_units": cash_amount,
                    "amount_scale": 0,
                    "instrument_id": "instrument-1",
                    "quantity_delta_units": None,
                    "quantity_delta_scale": None,
                },
                {
                    "event_time": T1,
                    "transaction_id": f"txn-{index}",
                    "idempotency_key": f"key-{index}",
                    "event_type": event_type,
                    "reference_id": cost_id,
                    "posting_index": 1,
                    "ledger_account": "expenses:cost",
                    "account_id": "acct-1",
                    "currency": BASE,
                    "amount_units": -cash_amount,
                    "amount_scale": 0,
                    "instrument_id": "instrument-1",
                    "quantity_delta_units": None,
                    "quantity_delta_scale": None,
                },
            ]
        )
    return _frame("costs", costs), _frame("cash_ledger", ledger)


def _write_run(
    run: Path,
    *,
    source: list[dict],
    costs: list[tuple[str, int, str | None]],
    nav_delta: int,
    market_impact_model: bool = False,
    include_v1: bool = False,
) -> None:
    cost_frame, ledger_frame = _cost_rows(costs)
    frames = {
        "returns": _frame(
            "returns",
            [
                {
                    "event_time": T0,
                    "strategy_id": "alpha",
                    "gross_return": 0.0,
                    "net_return": 0.0,
                    "nav_units": 1000,
                    "nav_scale": 0,
                    "base_currency": BASE,
                },
                {
                    "event_time": T1,
                    "strategy_id": "alpha",
                    "gross_return": 0.0,
                    "net_return": 0.0,
                    "nav_units": 1000 + nav_delta,
                    "nav_scale": 0,
                    "base_currency": BASE,
                },
            ],
        ),
        "positions": _frame(
            "positions",
            [
                {
                    "event_time": T0,
                    "account_id": "acct-1",
                    "strategy_id": "alpha",
                    "instrument_id": "instrument-1",
                    "quantity_units": 1,
                    "quantity_scale": 0,
                    "mark_price_units": 100,
                    "mark_price_scale": 0,
                    "market_value_units": 100,
                    "market_value_scale": 0,
                    "currency": BASE,
                    "fx_rate_units": 1,
                    "fx_rate_scale": 0,
                    "fx_snapshot_id": "fx-usd",
                    "base_market_value_units": 100,
                    "base_market_value_scale": 0,
                },
                {
                    "event_time": T1,
                    "account_id": "acct-1",
                    "strategy_id": "alpha",
                    "instrument_id": "instrument-1",
                    "quantity_units": 1,
                    "quantity_scale": 0,
                    "mark_price_units": 101,
                    "mark_price_scale": 0,
                    "market_value_units": 101,
                    "market_value_scale": 0,
                    "currency": BASE,
                    "fx_rate_units": 1,
                    "fx_rate_scale": 0,
                    "fx_snapshot_id": "fx-usd",
                    "base_market_value_units": 101,
                    "base_market_value_scale": 0,
                },
            ],
        ),
        "portfolio_snapshots": _frame(
            "portfolio_snapshots",
            [
                {
                    "event_time": event_time,
                    "account_id": "acct-1",
                    "base_currency": BASE,
                    "nav_units": nav,
                    "nav_scale": 0,
                    "cash_value_units": nav - 100,
                    "cash_value_scale": 0,
                    "market_value_units": 100,
                    "market_value_scale": 0,
                    "unrealized_pnl_units": 0,
                    "unrealized_pnl_scale": 0,
                    "realized_pnl_units": 0,
                    "realized_pnl_scale": 0,
                    "margin_used_units": 0,
                    "margin_used_scale": 0,
                }
                for event_time, nav in ((T0, 1000), (T1, 1000 + nav_delta))
            ],
        ),
        "exposures": _frame(
            "exposures",
            [
                {
                    "event_time": T1,
                    "account_id": "acct-1",
                    "strategy_id": "alpha",
                    "exposure_type": "signed_notional",
                    "name": "instrument-1",
                    "value": 101.0,
                    "unit": BASE,
                }
            ],
        ),
        "orders": _frame(
            "orders",
            [
                {
                    "event_time": T0,
                    "order_id": "order-1",
                    "idempotency_key": "order-key-1",
                    "account_id": "acct-1",
                    "strategy_id": "alpha",
                    "instrument_id": "instrument-1",
                    "side": "buy",
                    "quantity_units": 1,
                    "quantity_scale": 0,
                    "order_type": "market",
                    "limit_price_units": None,
                    "limit_price_scale": None,
                    "stop_price_units": None,
                    "stop_price_scale": None,
                    "time_in_force": "day",
                    "reduce_only": False,
                    "status": "filled",
                    "filled_quantity_units": 1,
                    "filled_quantity_scale": 0,
                    "version": 2,
                }
            ],
        ),
        "order_events": _frame(
            "order_events",
            [
                {
                    "event_time": T0,
                    "event_id": "accepted-1",
                    "order_id": "order-1",
                    "event_sequence": 1,
                    "from_status": "created",
                    "to_status": "accepted",
                    "fill_quantity_units": None,
                    "fill_quantity_scale": None,
                    "reason": "",
                },
                {
                    "event_time": T1,
                    "event_id": "filled-1",
                    "order_id": "order-1",
                    "event_sequence": 2,
                    "from_status": "accepted",
                    "to_status": "filled",
                    "fill_quantity_units": 1,
                    "fill_quantity_scale": 0,
                    "reason": "",
                },
            ],
        ),
        "fills": _frame(
            "fills",
            [
                {
                    "event_time": T1,
                    "fill_id": "fill-1",
                    "order_id": "order-1",
                    "account_id": "acct-1",
                    "strategy_id": "alpha",
                    "instrument_id": "instrument-1",
                    "side": "buy",
                    "quantity_units": 1,
                    "quantity_scale": 0,
                    "price_units": 101,
                    "price_scale": 0,
                    "currency": BASE,
                    "liquidity_role": "taker",
                    "venue_trade_id": "venue-1",
                }
            ],
        ),
        "costs": cost_frame,
        "cash_ledger": ledger_frame,
        "margin": _frame(
            "margin",
            [
                {
                    "event_time": T1,
                    "account_id": "acct-1",
                    "instrument_id": "instrument-1",
                    "initial_margin_units": 0,
                    "maintenance_margin_units": 0,
                    "margin_scale": 0,
                    "currency": BASE,
                }
            ],
        ),
        "attribution": _frame("attribution", source),
    }
    if include_v1:
        write_standard_run(
            run,
            project="legacy",
            run_id=run.name,
            strategy="legacy",
            frames={},
            metrics={},
            config={},
            code_version="legacy",
        )
    lineage = {name: ["dataset:fixture"] for name in frames}
    lineage["config"] = []
    lineage["metrics"] = ["dataset:fixture"]
    write_standard_run_v2(
        run,
        project="m5-golden",
        run_id=run.name,
        strategy_ids=["alpha"],
        profile=BACKTEST_LEDGER_PROFILE,
        frames=frames,
        metrics={"fixture": True},
        config={"market_impact_model_version": "sqrt-v1"} if market_impact_model else {},
        code_version="a" * 40,
        internal_dependencies={"quant-lab": "v0.3.0"},
        random_seed=7,
        dataset_snapshots={"fixture": "sha256:golden-v1"},
        instrument_master_version="fixture-master-v1",
        execution_model_version="fixture-execution-v1",
        base_currency=BASE,
        lineage=lineage,
        created_at="2025-01-04T00:00:00+00:00",
    )


def _references(*, available_at: pd.Timestamp = T0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fill_id": "fill-1",
                "reference_time": T0,
                "available_at": available_at,
                "reference_price_units": 100,
                "reference_price_scale": 0,
                "multiplier_units": 1,
                "multiplier_scale": 0,
                "fx_rate_units": 1,
                "fx_rate_scale": 0,
                "base_currency": BASE,
            }
        ]
    )


def _run_and_read(run: Path, *, references: pd.DataFrame | None = None):
    report = run / "m5-report"
    manifest = reconcile_standard_run_v2(run, out_dir=report, slippage_references=references)
    return (
        manifest,
        pd.read_csv(report / "attribution.csv"),
        pd.read_csv(report / "reconciliation.csv"),
    )


def test_a_share_commission_and_tax_golden_reconcile_all_levels(tmp_path: Path):
    run = tmp_path / "a-share"
    _write_run(
        run,
        source=[_source_row("price", 20)],
        costs=[("commission", 7, "fill-1"), ("tax", 3, "fill-1")],
        nav_delta=10,
    )
    manifest, detail, reconciliation = _run_and_read(run)
    assert manifest.reconciliation == {"account": 1, "portfolio": 1, "strategy": 1, "instrument": 1}
    assert set(detail["component"]) == {"price", "commission", "tax"}
    assert reconciliation["status"].eq("pass").all()
    assert set(reconciliation["level"]) == {"account", "portfolio", "strategy", "instrument"}


def test_futures_price_carry_roll_and_settlement_golden_reconcile(tmp_path: Path):
    run = tmp_path / "futures"
    _write_run(
        run,
        source=[_source_row("price", 15), _source_row("carry", 3), _source_row("roll", 2)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=19,
    )
    _, detail, _ = _run_and_read(run)
    assert {
        component: sum(map(int, rows["base_amount_units"]))
        for component, rows in detail.groupby("component")
    } == {
        "carry": 3 * 10**18,
        "commission": -(10**18),
        "price": 15 * 10**18,
        "roll": 2 * 10**18,
    }


def test_crypto_maker_taker_funding_fx_and_slippage_golden(tmp_path: Path):
    run = tmp_path / "crypto"
    _write_run(
        run,
        source=[_source_row("price", 20), _source_row("fx", 5)],
        costs=[
            ("maker_fee", 1, "fill-1"),
            ("taker_fee", 1, "fill-1"),
            ("funding", 2, None),
            ("slippage", 1, "fill-1"),
        ],
        nav_delta=20,
    )
    _, detail, _ = _run_and_read(run, references=_references())
    values = {
        component: sum(map(int, rows["base_amount_units"]))
        for component, rows in detail.groupby("component")
    }
    assert values == {
        "funding": -2 * 10**18,
        "fx": 5 * 10**18,
        "maker_fee": -(10**18),
        "price": 20 * 10**18,
        "slippage": -(10**18),
        "taker_fee": -(10**18),
    }


def test_market_impact_requires_frozen_model_version(tmp_path: Path):
    run = tmp_path / "impact"
    _write_run(
        run, source=[_source_row("price", 9)], costs=[("market_impact", 1, "fill-1")], nav_delta=8
    )
    with pytest.raises(V2AttributionError, match="market_impact_model_version"):
        _run_and_read(run)


def test_residual_exceeding_threshold_fails_publication(tmp_path: Path):
    run = tmp_path / "residual"
    _write_run(
        run, source=[_source_row("price", 1)], costs=[("commission", 1, "fill-1")], nav_delta=2
    )
    with pytest.raises(V2AttributionError, match="残差"):
        _run_and_read(run)


def test_source_residual_cannot_mask_an_unexplained_nav_change(tmp_path: Path):
    run = tmp_path / "masked-residual"
    _write_run(
        run,
        source=[_source_row("price", 2), _source_row("residual", 1)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=2,
    )
    with pytest.raises(V2AttributionError, match="残差component超过阈值"):
        _run_and_read(run)


def test_attribution_outside_a_nav_interval_is_not_silently_ignored(tmp_path: Path):
    run = tmp_path / "extra-interval"
    extra = _source_row("carry", 1)
    extra["event_time"] = T0
    _write_run(
        run,
        source=[extra, _source_row("price", 11)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=10,
    )
    with pytest.raises(V2AttributionError, match="account归因残差"):
        _run_and_read(run)


def test_cost_currency_and_scale_mismatch_fails_exact_reconciliation(tmp_path: Path):
    run = tmp_path / "bad-cost"
    _write_run(
        run, source=[_source_row("price", 10)], costs=[("commission", 1, "fill-1")], nav_delta=9
    )
    costs_path = run / "standard" / "v2" / "costs.parquet"
    costs = pd.read_parquet(costs_path)
    costs.loc[0, "amount_units"] = 2
    costs.to_parquet(costs_path, index=False)
    with pytest.raises(ValueError, match="mutated"):
        _run_and_read(run)


def test_v2_hash_corruption_never_falls_back_to_v1(tmp_path: Path):
    run = tmp_path / "mutated"
    _write_run(
        run,
        source=[_source_row("price", 11)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=10,
        include_v1=True,
    )
    metrics = run / "standard" / "v2" / "metrics.json"
    metrics.write_text(json.dumps({"mutated": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="mutated"):
        _run_and_read(run)
    with pytest.raises(ValueError, match="mutated"):
        v2.attribute_standard_run(run, pd.DataFrame(), out_dir=run / "auto-report")


def test_public_attribution_entry_prefers_v2_when_v1_also_exists(tmp_path: Path):
    run = tmp_path / "dual-read"
    _write_run(
        run,
        source=[_source_row("price", 11)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=10,
        include_v1=True,
    )
    result = v2.attribute_standard_run(run, pd.DataFrame(), out_dir=run / "preferred-report")
    assert isinstance(result, v2.V2AttributionManifest)
    assert result.source_schema_version == "2.0.0"


def test_duplicate_primary_key_is_rejected_before_consumer_can_read(tmp_path: Path):
    run = tmp_path / "duplicate"
    _write_run(
        run,
        source=[_source_row("price", 11)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=10,
    )
    source = pd.read_parquet(run / "standard" / "v2" / "attribution.parquet")
    duplicate = pd.concat([source, source], ignore_index=True)
    assert duplicate.duplicated(
        ["event_time", "account_id", "strategy_id", "instrument_id", "component"]
    ).any()


def test_future_reference_and_missing_slippage_reference_fail(tmp_path: Path):
    run = tmp_path / "future-reference"
    _write_run(
        run, source=[_source_row("price", 9)], costs=[("slippage", 1, "fill-1")], nav_delta=8
    )
    with pytest.raises(V2AttributionError, match="因果reference"):
        _run_and_read(run)
    with pytest.raises(V2AttributionError, match="违反PIT"):
        _run_and_read(run, references=_references(available_at=T1 + pd.Timedelta(seconds=1)))


def test_three_reconciliations_are_deterministic(tmp_path: Path):
    manifests = []
    outputs = []
    for index in range(3):
        run = tmp_path / f"deterministic-{index}"
        _write_run(
            run,
            source=[_source_row("price", 20)],
            costs=[("commission", 10, "fill-1")],
            nav_delta=10,
        )
        manifest, _, _ = _run_and_read(run)
        manifests.append(manifest.files)
        outputs.append((run / "m5-report" / "attribution.csv").read_bytes())
    assert manifests[0] == manifests[1] == manifests[2]
    assert outputs[0] == outputs[1] == outputs[2]


def test_fixed_point_and_time_guards_reject_imprecise_or_non_utc_inputs():
    assert v2._decimal_from_fixed(123, 2, "amount") == v2.Decimal("1.23")
    assert v2._fixed_from_decimal(v2.Decimal("1.23"), 2) == (123, 2)
    with pytest.raises(V2AttributionError):
        v2._decimal_from_fixed(True, 2, "amount")
    with pytest.raises(V2AttributionError):
        v2._decimal_from_fixed(1.2, 2, "amount")
    with pytest.raises(V2AttributionError):
        v2._decimal_from_fixed(1, 2.5, "amount")
    with pytest.raises(V2AttributionError):
        v2._decimal_from_fixed(1, 19, "amount")
    with pytest.raises(V2AttributionError):
        v2._fixed_from_decimal(v2.Decimal("0.001"), 2)
    with pytest.raises(V2AttributionError):
        v2._fixed_from_decimal(v2.Decimal("NaN"))
    with pytest.raises(V2AttributionError):
        v2._parse_utc("2025-01-01", "time")
    with pytest.raises(V2AttributionError):
        v2._parse_utc("2025-01-01T00:00:00+08:00", "time")


def test_source_component_and_reference_validation_guards(tmp_path: Path):
    run = tmp_path / "guards"
    _write_run(
        run, source=[_source_row("price", 11)], costs=[("commission", 1, "fill-1")], nav_delta=10
    )
    _, _, frames, _ = v2._read_validated_v2(run)
    with pytest.raises(V2AttributionError, match="缺少字段"):
        v2._require_frame_columns(pd.DataFrame(), "empty", {"required"})
    assert v2._source_components(pd.DataFrame(), BASE) == []
    with pytest.raises(V2AttributionError, match="不受支持"):
        v2._component_record(
            event_time=T1,
            account_id="acct-1",
            strategy_id="alpha",
            instrument_id="instrument-1",
            component="unknown",
            currency=BASE,
            amount=v2.Decimal(0),
            base_currency=BASE,
            base_amount=v2.Decimal(0),
        )
    source = frames["attribution"].copy()
    source.loc[0, "component"] = "unknown"
    with pytest.raises(V2AttributionError, match="未冻结"):
        v2._source_components(source, BASE)
    source = frames["attribution"].copy()
    source.loc[0, "base_currency"] = "CNY"
    with pytest.raises(V2AttributionError, match="base_currency"):
        v2._source_components(source, BASE)
    source = frames["attribution"].copy()
    source.loc[0, "base_amount_units"] = 12
    with pytest.raises(V2AttributionError, match="精确相等"):
        v2._source_components(source, BASE)
    duplicate = pd.concat([_references(), _references()], ignore_index=True)
    with pytest.raises(V2AttributionError, match="必须唯一"):
        v2._reference_slippage(frames["fills"], duplicate, BASE)
    wrong_base = _references()
    wrong_base.loc[0, "base_currency"] = "CNY"
    with pytest.raises(V2AttributionError, match="base_currency"):
        v2._reference_slippage(frames["fills"], wrong_base, BASE)
    bad_multiplier = _references()
    bad_multiplier.loc[0, "multiplier_units"] = 0
    with pytest.raises(V2AttributionError, match="必须为正"):
        v2._reference_slippage(frames["fills"], bad_multiplier, BASE)
    bad_side = frames["fills"].copy()
    bad_side.loc[0, "side"] = "unknown"
    with pytest.raises(V2AttributionError, match="buy或sell"):
        v2._reference_slippage(bad_side, _references(), BASE)
    unmatched_fill = frames["fills"].copy()
    unmatched_fill.loc[0, "fill_id"] = "not-referenced"
    assert v2._reference_slippage(unmatched_fill, _references(), BASE) == {}
    zero_quantity = frames["fills"].copy()
    zero_quantity.loc[0, "quantity_units"] = 0
    with pytest.raises(V2AttributionError, match="必须为正"):
        v2._reference_slippage(zero_quantity, _references(), BASE)
    favourable = _references()
    favourable.loc[0, "reference_price_units"] = 102
    with pytest.raises(V2AttributionError, match="有利成交"):
        v2._reference_slippage(frames["fills"], favourable, BASE)


def test_cost_ledger_and_nonbase_currency_validation_guards(tmp_path: Path):
    run = tmp_path / "cost-guards"
    _write_run(
        run, source=[_source_row("price", 11)], costs=[("commission", 1, "fill-1")], nav_delta=10
    )
    _, _, frames, _ = v2._read_validated_v2(run)
    source = v2._source_components(frames["attribution"], BASE)
    bad_type = frames["costs"].copy()
    bad_type.loc[0, "cost_type"] = "borrow_cost"
    with pytest.raises(V2AttributionError, match="未被M5受控"):
        v2._cost_records(bad_type, frames["cash_ledger"], source, frames["fills"], None, BASE, {})
    missing_ledger = frames["cash_ledger"].iloc[0:0]
    with pytest.raises(V2AttributionError, match="缺少"):
        v2._cost_records(frames["costs"], missing_ledger, source, frames["fills"], None, BASE, {})
    nonbase = frames["costs"].copy()
    nonbase.loc[0, "currency"] = "CNY"
    with pytest.raises(V2AttributionError, match="缺少对应"):
        v2._cost_records(nonbase, frames["cash_ledger"], source, frames["fills"], None, BASE, {})
    impact = frames["costs"].copy()
    impact.loc[0, "cost_type"] = "market_impact"
    with pytest.raises(V2AttributionError, match="market_impact_model_version"):
        v2._cost_records(impact, frames["cash_ledger"], source, frames["fills"], None, BASE, {})
    extra_ledger = pd.concat(
        [
            frames["cash_ledger"],
            pd.DataFrame(
                [
                    {
                        **frames["cash_ledger"].iloc[0].to_dict(),
                        "reference_id": "unexplained-fee",
                        "transaction_id": "unexplained-txn",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(V2AttributionError, match="未被costs解释"):
        v2._cost_records(
            frames["costs"], extra_ledger, source, frames["fills"], None, BASE, {}
        )
    negative = frames["costs"].copy()
    negative.loc[0, "amount_units"] = -1
    with pytest.raises(V2AttributionError, match="非负"):
        v2._cost_records(negative, frames["cash_ledger"], source, frames["fills"], None, BASE, {})
    fee_mismatch = frames["cash_ledger"].copy()
    fee_mismatch.loc[fee_mismatch["ledger_account"].eq("assets:cash"), "amount_units"] = -2
    with pytest.raises(V2AttributionError, match="不精确相等"):
        v2._cost_records(
            frames["costs"], fee_mismatch, source, frames["fills"], None, BASE, {}
        )
    funding_cost = frames["costs"].copy()
    funding_cost.loc[0, "cost_type"] = "funding"
    funding_ledger = frames["cash_ledger"].copy()
    funding_ledger.loc[:, "event_type"] = "funding"
    funding_ledger.loc[
        funding_ledger["ledger_account"].eq("assets:cash"), "amount_units"
    ] = -2
    with pytest.raises(V2AttributionError, match="funding"):
        v2._cost_records(
            funding_cost, funding_ledger, source, frames["fills"], None, BASE, {}
        )
    slippage = frames["costs"].copy()
    slippage.loc[0, "cost_type"] = "slippage"
    slippage.loc[0, "amount_units"] = 2
    slippage_ledger = frames["cash_ledger"].copy()
    slippage_ledger.loc[
        slippage_ledger["ledger_account"].eq("assets:cash"), "amount_units"
    ] = -2
    with pytest.raises(V2AttributionError, match="reference/fill"):
        v2._cost_records(
            slippage,
            slippage_ledger,
            source,
            frames["fills"],
            _references(),
            BASE,
            {},
        )
    with pytest.raises(V2AttributionError, match="必须有对应"):
        v2._cost_records(
            frames["costs"],
            frames["cash_ledger"],
            source,
            frames["fills"],
            _references(),
            BASE,
            {},
        )
    nonbase_ledger = frames["cash_ledger"].copy()
    nonbase_ledger.loc[:, "currency"] = "CNY"
    with pytest.raises(V2AttributionError, match="base_amount"):
        v2._cost_records(nonbase, nonbase_ledger, source, frames["fills"], None, BASE, {})
    mismatched_source = [
        v2._component_record(
            event_time=T1,
            account_id="acct-1",
            strategy_id="alpha",
            instrument_id="instrument-1",
            component="commission",
            currency="CNY",
            amount=v2.Decimal("-2"),
            base_currency=BASE,
            base_amount=v2.Decimal("-0.4"),
        )
    ]
    with pytest.raises(V2AttributionError, match="金额与现金账本不一致"):
        v2._cost_records(
            nonbase,
            nonbase_ledger,
            mismatched_source,
            frames["fills"],
            None,
            BASE,
            {},
        )


def test_v2_report_rejects_source_mutation_and_untraceable_components(tmp_path: Path):
    forbidden_run = tmp_path / "forbidden"
    _write_run(
        forbidden_run,
        source=[_source_row("price", 11)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=10,
    )
    for destination in (
        forbidden_run / "standard" / "v2" / "injected-report",
        forbidden_run / "standard" / "v2" / ".." / "traversal-report",
    ):
        with pytest.raises(V2AttributionError, match="standard"):
            reconcile_standard_run_v2(forbidden_run, out_dir=destination)

    unmatched = tmp_path / "unmatched-cost"
    _write_run(
        unmatched,
        source=[_source_row("price", 11), _source_row("tax", -999)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=10,
    )
    with pytest.raises(V2AttributionError, match="成本component"):
        reconcile_standard_run_v2(unmatched, out_dir=tmp_path / "unmatched-report")

    phantom = tmp_path / "phantom"
    phantom_price = _source_row("price", 11)
    phantom_price["instrument_id"] = "instrument-not-in-any-source-artifact"
    _write_run(
        phantom,
        source=[phantom_price],
        costs=[("commission", 1, "fill-1")],
        nav_delta=10,
    )
    with pytest.raises(V2AttributionError, match="无法追溯"):
        reconcile_standard_run_v2(phantom, out_dir=tmp_path / "phantom-report")


def test_nav_delta_sources_reject_mixed_base_currencies(tmp_path: Path):
    run = tmp_path / "mixed-base-currency"
    _write_run(
        run,
        source=[_source_row("price", 11)],
        costs=[("commission", 1, "fill-1")],
        nav_delta=10,
    )
    _, _, frames, _ = v2._read_validated_v2(run)

    snapshots = frames["portfolio_snapshots"].copy()
    snapshots.loc[0, "base_currency"] = "CNY"
    with pytest.raises(V2AttributionError, match="portfolio_snapshots.base_currency"):
        v2._snapshot_deltas(snapshots, BASE)

    returns = frames["returns"].copy()
    returns.loc[0, "base_currency"] = "CNY"
    with pytest.raises(V2AttributionError, match="returns.base_currency"):
        v2._strategy_deltas(returns, BASE)


def test_report_destination_is_immutable_and_v1_is_not_a_v2_input(tmp_path: Path):
    run = tmp_path / "published"
    _write_run(
        run, source=[_source_row("price", 11)], costs=[("commission", 1, "fill-1")], nav_delta=10
    )
    _run_and_read(run)
    with pytest.raises(FileExistsError, match="拒绝改写"):
        _run_and_read(run)
    legacy = tmp_path / "legacy"
    write_standard_run(
        legacy,
        project="legacy",
        run_id="legacy",
        strategy="legacy",
        frames={},
        metrics={},
        config={},
        code_version="legacy",
    )
    with pytest.raises(V2AttributionError, match="只接受"):
        reconcile_standard_run_v2(legacy, out_dir=tmp_path / "legacy-report")


def test_nonbase_cost_and_funding_paths_are_exact(tmp_path: Path):
    run = tmp_path / "currency"
    _write_run(
        run, source=[_source_row("price", 11)], costs=[("commission", 1, "fill-1")], nav_delta=10
    )
    _, _, frames, _ = v2._read_validated_v2(run)
    costs = frames["costs"].copy()
    costs.loc[0, "currency"] = "CNY"
    ledger = frames["cash_ledger"].copy()
    ledger.loc[:, "currency"] = "CNY"
    cost_source = [
        v2._component_record(
            event_time=T1,
            account_id="acct-1",
            strategy_id="alpha",
            instrument_id="instrument-1",
            component="commission",
            currency="CNY",
            amount=v2.Decimal("-1"),
            base_currency=BASE,
            base_amount=v2.Decimal("-0.2"),
        )
    ]
    result = v2._cost_records(costs, ledger, cost_source, frames["fills"], None, BASE, {})
    assert result[0]["base_amount"] == v2.Decimal("-0.2")
    costs.loc[0, "cost_type"] = "funding"
    ledger.loc[:, "event_type"] = "funding"
    funding_source = [dict(cost_source[0], component="funding")]
    result = v2._cost_records(costs, ledger, funding_source, frames["fills"], None, BASE, {})
    assert result[0]["amount"] == v2.Decimal("-1")


def test_legacy_attribution_optional_outputs_and_validation(tmp_path: Path):
    positions = pd.DataFrame(
        {"date": ["2025-01-01"], "strategy": ["alpha"], "symbol": ["A"], "weight": [1.0]}
    )
    returns = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "strategy": ["alpha"],
            "gross_return": [0.1],
            "net_return": [0.09],
        }
    )
    costs = pd.DataFrame({"date": ["2025-01-02"], "strategy": ["alpha"], "total_cost": [0.01]})
    exposures = pd.DataFrame(
        {
            "date": ["2025-01-01"],
            "strategy": ["alpha"],
            "exposure_type": ["factor"],
            "name": ["market"],
            "value": [1.0],
        }
    )
    write_standard_run(
        tmp_path,
        project="legacy",
        run_id="legacy",
        strategy="alpha",
        frames={"positions": positions, "returns": returns, "costs": costs, "exposures": exposures},
        metrics={},
        config={},
        code_version="legacy",
    )
    asset_returns = pd.DataFrame({"date": ["2025-01-02"], "symbol": ["A"], "return": [0.1]})
    from quant_report_hub.attribution import (
        attribute_standard_run,
        factor_attribution,
        holdings_attribution,
    )

    manifest = attribute_standard_run(
        tmp_path,
        asset_returns,
        factor_returns=pd.DataFrame({"date": ["2025-01-02"], "name": ["market"], "return": [0.1]}),
        benchmark_positions=positions.drop(columns="strategy"),
        classifications=pd.DataFrame({"symbol": ["A"], "group": ["all"]}),
        allow_same_day_positions=True,
    )
    assert {"factors.csv", "factor_summary.csv", "brinson.csv"} <= set(manifest.files)
    with pytest.raises(ValueError, match="必须唯一"):
        holdings_attribution(pd.concat([positions, positions]), asset_returns)
    with pytest.raises(ValueError, match="必须唯一"):
        factor_attribution(
            exposures,
            pd.concat(
                [
                    asset_returns.rename(columns={"symbol": "name"}),
                    asset_returns.rename(columns={"symbol": "name"}),
                ]
            ),
        )


def test_reconcile_v2_cli_publishes_to_explicit_report_directory(tmp_path: Path):
    run = tmp_path / "cli"
    _write_run(run, source=[_source_row("price", 11)], costs=[("commission", 1, "fill-1")], nav_delta=10)
    destination = tmp_path / "cli-report"
    assert main(["reconcile-v2", "--run-dir", str(run), "--out-dir", str(destination)]) == 0
    assert (destination / "manifest.json").is_file()
    assert main(["compare", "--output-root", str(tmp_path), "--run-ids", "only-one"]) == 1
