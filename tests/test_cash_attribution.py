from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from quant_lab.contracts_v2 import ARTIFACT_SCHEMAS_V2, write_standard_run_v2

from quant_report_hub.cash_attribution import _reconstruct, reconcile_cash_ledger_v2
from quant_report_hub.cli import main

T0 = pd.Timestamp("2025-01-02T07:00:00Z")
SPLIT = T0 + pd.Timedelta(days=1)
ACCRUAL = SPLIT + pd.Timedelta(seconds=1)
SALE = T0 + pd.Timedelta(days=2)
PAYMENT = T0 + pd.Timedelta(days=3)
INSTRUMENT = "fund@opaque"


def _frames():
    rows = {
        name: []
        for name in (
            "returns",
            "positions",
            "portfolio_snapshots",
            "orders",
            "order_events",
            "fills",
            "costs",
            "cash_ledger",
            "margin",
            "exposures",
        )
    }

    def posting(account, amount, instrument=None, quantity=None):
        return {
            "ledger_account": account,
            "amount_units": int(Decimal(str(amount)) * 100),
            "amount_scale": 2,
            "instrument_id": instrument,
            "quantity_delta_units": quantity,
            "quantity_delta_scale": 0 if quantity is not None else None,
        }

    def transaction(stamp, kind, ref, entries):
        for i, entry in enumerate(entries):
            rows["cash_ledger"].append(
                {
                    "event_time": stamp,
                    "transaction_id": ref,
                    "idempotency_key": ref,
                    "event_type": kind,
                    "reference_id": ref,
                    "posting_index": i,
                    "account_id": "account",
                    "currency": "CNY",
                    **entry,
                }
            )

    transaction(
        T0,
        "fx_conversion",
        "opening:CNY",
        [posting("assets:cash", 1000), posting("equity:opening", -1000)],
    )
    for stamp, ref, side, qty, price, fee, role in (
        (T0, "buy", "buy", 10, "10", 1, "taker"),
        (SALE, "sell", "sell", 20, "6.2", 2, "maker"),
    ):
        sign = 1 if side == "buy" else -1
        cash = -sign * qty * Decimal(price)
        entries = [
            posting("assets:cash", cash),
            posting("assets:position_cost", 100 * sign, INSTRUMENT),
        ]
        if side == "sell":
            entries.append(posting("income:realized_pnl", -24, INSTRUMENT))
        entries.extend(
            [
                posting("assets:position", 0, INSTRUMENT, sign * qty),
                posting("memo:position_counter", 0, INSTRUMENT, -sign * qty),
            ]
        )
        transaction(stamp, "fill", ref, entries)
        transaction(
            stamp,
            "fee",
            "fee-" + ref,
            [posting("assets:cash", -fee), posting("expenses:fees", fee)],
        )
        rows["fills"].append(
            {
                "event_time": stamp,
                "fill_id": ref,
                "order_id": ref,
                "account_id": "account",
                "strategy_id": "strategy",
                "instrument_id": INSTRUMENT,
                "side": side,
                "quantity_units": qty,
                "quantity_scale": 0,
                "price_units": int(Decimal(price) * 100),
                "price_scale": 2,
                "currency": "CNY",
                "liquidity_role": role,
                "venue_trade_id": ref,
            }
        )
        rows["costs"].append(
            {
                "event_time": stamp,
                "cost_id": "fee-" + ref,
                "account_id": "account",
                "strategy_id": "strategy",
                "instrument_id": INSTRUMENT,
                "fill_id": ref,
                "cost_type": role,
                "amount_units": fee,
                "amount_scale": 0,
                "currency": "CNY",
            }
        )
        rows["orders"].append(
            {
                "event_time": stamp,
                "order_id": ref,
                "idempotency_key": ref,
                "account_id": "account",
                "strategy_id": "strategy",
                "instrument_id": INSTRUMENT,
                "side": side,
                "quantity_units": qty,
                "quantity_scale": 0,
                "order_type": "market",
                "time_in_force": "day",
                "reduce_only": False,
                "status": "filled",
                "filled_quantity_units": qty,
                "filled_quantity_scale": 0,
                "version": 2,
            }
        )
        for sequence, before, after in ((1, "created", "accepted"), (2, "accepted", "filled")):
            rows["order_events"].append(
                {
                    "event_time": stamp,
                    "event_id": f"{ref}-{sequence}",
                    "order_id": ref,
                    "event_sequence": sequence,
                    "from_status": before,
                    "to_status": after,
                    "fill_quantity_units": qty if sequence == 2 else None,
                    "fill_quantity_scale": 0 if sequence == 2 else None,
                    "reason": "",
                }
            )
    transaction(
        SPLIT,
        "corporate_action",
        "split",
        [
            posting("assets:position", 0, INSTRUMENT, 10),
            posting("memo:position_counter", 0, INSTRUMENT, -10),
        ],
    )
    transaction(
        ACCRUAL,
        "corporate_action",
        "entitlement",
        [
            posting("assets:dividend_receivable", 10, "opaque-entitlement-key"),
            posting("income:corporate_action", -10, INSTRUMENT),
        ],
    )
    transaction(
        PAYMENT,
        "corporate_action",
        "payment",
        [
            posting("assets:cash", 10),
            posting("assets:dividend_receivable", -10, "opaque-entitlement-key"),
        ],
    )
    prior = 1000
    for stamp, cash, quantity, price, nav in (
        (T0, 899, 10, "11", 1009),
        (SPLIT, 899, 20, "5.5", 1009),
        (ACCRUAL, 899, 20, "6", 1029),
        (SALE, 1021, 0, "6.2", 1031),
        (PAYMENT, 1031, 0, "6.2", 1031),
    ):
        mv = quantity * Decimal(price)
        rows["portfolio_snapshots"].append(
            {
                "event_time": stamp,
                "account_id": "account",
                "base_currency": "CNY",
                **{
                    field + suffix: value if suffix == "_units" else 0
                    for field, value in {
                        "nav": nav,
                        "cash_value": cash,
                        "market_value": int(mv),
                        "unrealized_pnl": 0,
                        "realized_pnl": 0,
                        "margin_used": 0,
                    }.items()
                    for suffix in ("_units", "_scale")
                },
            }
        )
        if quantity:
            rows["positions"].append(
                {
                    "event_time": stamp,
                    "account_id": "account",
                    "strategy_id": "strategy",
                    "instrument_id": INSTRUMENT,
                    "quantity_units": quantity,
                    "quantity_scale": 0,
                    "mark_price_units": int(Decimal(price) * 100),
                    "mark_price_scale": 2,
                    "market_value_units": int(mv),
                    "market_value_scale": 0,
                    "currency": "CNY",
                    "fx_rate_units": 1,
                    "fx_rate_scale": 0,
                    "fx_snapshot_id": "cash-CNY",
                    "base_market_value_units": int(mv),
                    "base_market_value_scale": 0,
                }
            )
        if stamp != SPLIT:
            rows["returns"].append(
                {
                    "event_time": stamp,
                    "strategy_id": "strategy",
                    "base_currency": "CNY",
                    "nav_units": nav,
                    "nav_scale": 0,
                    "net_return": nav / prior - 1,
                    "gross_return": 0.0,
                }
            )
            prior = nav
    frames = {
        name: pd.DataFrame(values, columns=ARTIFACT_SCHEMAS_V2[name])
        for name, values in rows.items()
    }
    for field in ("quantity_delta_units", "quantity_delta_scale"):
        frames["cash_ledger"][field] = frames["cash_ledger"][field].astype("Int64")
    return frames


def _manifest():
    return SimpleNamespace(
        profile="backtest-ledger", strategy_ids=["strategy"], base_currency="CNY"
    )


def _write(run, frames):
    frames = {
        name: frame.sort_values("event_time", kind="stable") for name, frame in frames.items()
    }
    write_standard_run_v2(
        run,
        project="cash-ledger-test",
        run_id=run.name,
        strategy_ids=["strategy"],
        profile="backtest-ledger",
        frames=frames,
        metrics={},
        config={},
        code_version="a" * 40,
        internal_dependencies={"quant-lab": "v0.3.0"},
        random_seed=0,
        dataset_snapshots={"fixture": "sha256:cash-v1"},
        instrument_master_version="test",
        execution_model_version="test",
        base_currency="CNY",
        lineage={
            **{name: ["dataset:fixture"] for name in frames},
            "config": [],
            "metrics": ["dataset:fixture"],
        },
        created_at="2025-01-08T00:00:00+00:00",
    )


def test_first_day_split_dividend_receivable_sale_and_payment(tmp_path):
    source, target = tmp_path / "source", tmp_path / "report"
    _write(source, _frames())
    before = {
        p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in source.rglob("*")
        if p.is_file()
    }
    result = reconcile_cash_ledger_v2(source, out_dir=target)
    periods = pd.read_csv(target / "period_reconciliation.csv")
    assert periods.net_pnl.tolist() == [9, 20, 2, 0]
    assert periods.valuation_and_trading_pnl.tolist() == [10, 10, 4, 0]
    assert periods.corporate_income.tolist() == [0, 10, 0, 0]
    assert periods.dividend_receivable.tolist() == [0, 10, 10, 0]
    assert periods.fee_cash.tolist() == [-1, 0, -2, 0]
    assert periods.residual.eq(0).all()
    assert result["summary"]["closing_nav"] == "1031"
    assert result["row_counts"]["event_reconciliation.csv"] == 5
    assert pd.read_csv(target / "fee_details.csv").cost_type.tolist() == ["taker", "maker"]
    detail = pd.read_csv(target / "instrument_pnl.csv")
    assert detail.instrument_id.eq(INSTRUMENT).all()
    assert detail.return_contribution.iloc[0] == pytest.approx(0.009)
    assert "现金机会成本" in (target / "report.html").read_text(encoding="utf-8")
    assert json.loads((target / "manifest.json").read_text(encoding="utf-8")) == result
    for name, digest in result["files"].items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == digest
    assert before == {
        p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in before
    }
    assert main(["cash-attribution", "--run-dir", str(source), "--out-dir", str(target)]) == 1
    with pytest.raises(ValueError, match="源运行目录之外"):
        reconcile_cash_ledger_v2(source, out_dir=source / "new-report")


@pytest.mark.parametrize(
    "name,column,index,value,message",
    [
        ("cash_ledger", "amount_units", 0, 99999, "借贷不平"),
        ("cash_ledger", "posting_index", 0, 1, "分录序号"),
        ("cash_ledger", "quantity_delta_units", 4, 9, "数量借贷不平"),
        ("positions", "quantity_units", 0, 9, "估值"),
        ("positions", "fx_rate_units", 0, 2, "FX"),
        ("positions", "account_id", 0, "other", "单账户"),
        ("portfolio_snapshots", "cash_value_units", 0, 900, "现金余额"),
        ("portfolio_snapshots", "market_value_units", 0, 109, "估值合计"),
        ("portfolio_snapshots", "nav_units", 0, 1010, "NAV不等于"),
        ("portfolio_snapshots", "margin_used_units", 0, 1, "保证金"),
        ("returns", "nav_units", 0, 1010, "收益表NAV"),
        ("returns", "net_return", 0, 0, "净收益率"),
        ("costs", "amount_units", 0, 2, "费用表"),
        ("costs", "instrument_id", 0, "other", "费用和成交"),
        ("costs", "cost_type", 0, "", "分类为空"),
        ("fills", "price_units", 0, 1001, "名义金额"),
        ("fills", "side", 0, "unknown", "方向无效"),
        ("cash_ledger", "event_type", 0, "funding", "不一致"),
    ],
)
def test_rejects_accounting_inconsistencies(name, column, index, value, message):
    frames = _frames()
    frames[name].loc[index, column] = value
    with pytest.raises(ValueError, match=message):
        _reconstruct(_manifest(), frames)


def test_corrupted_source_rejected_before_publication(tmp_path):
    source, target = tmp_path / "source", tmp_path / "out"
    _write(source, _frames())
    (source / "standard/v2/returns.parquet").write_bytes(b"corrupted")
    assert main(["cash-attribution", "--run-dir", str(source), "--out-dir", str(target)]) == 1
    assert not target.exists()


def test_semantic_corruption_with_valid_hash_is_rejected(tmp_path):
    frames = _frames()
    frames["returns"].loc[0, "net_return"] = 0
    source, target = tmp_path / "source", tmp_path / "out"
    _write(source, frames)
    with pytest.raises(ValueError, match="净收益率"):
        reconcile_cash_ledger_v2(source, out_dir=target)
    assert not target.exists()


def test_missing_snapshot_and_trailing_return_boundary():
    frames = _frames()
    frames["returns"] = frames["returns"].iloc[:-1]
    with pytest.raises(ValueError, match="最后快照"):
        _reconstruct(_manifest(), frames)
    frames = _frames()
    frames["portfolio_snapshots"] = frames["portfolio_snapshots"].iloc[1:]
    with pytest.raises(ValueError, match="精确时点快照"):
        _reconstruct(_manifest(), frames)


def test_payment_before_entitlement_and_unbooked_fill():
    frames = _frames()
    frames["cash_ledger"].loc[frames["cash_ledger"].reference_id.eq("payment"), "event_time"] = T0
    with pytest.raises(ValueError, match="先于权益确认"):
        _reconstruct(_manifest(), frames)
    frames = _frames()
    frames["cash_ledger"] = frames["cash_ledger"][~frames["cash_ledger"].reference_id.eq("buy")]
    with pytest.raises(ValueError, match="成交未记入"):
        _reconstruct(_manifest(), frames)


def _refresh_returns(frames):
    previous = 1000
    for i, row in frames["returns"].iterrows():
        nav = frames["portfolio_snapshots"].set_index("event_time").loc[row.event_time, "nav_units"]
        frames["returns"].loc[i, "nav_units"] = nav
        frames["returns"].loc[i, "net_return"] = nav / previous - 1
        previous = nav


def test_direct_cash_dividend_without_receivable():
    frames = _frames()
    ledger = frames["cash_ledger"]
    frames["cash_ledger"] = ledger[~ledger.reference_id.eq("payment")].copy()
    due = frames["cash_ledger"].ledger_account.eq("assets:dividend_receivable")
    frames["cash_ledger"].loc[due, "ledger_account"] = "assets:cash"
    frames["cash_ledger"].loc[due, "instrument_id"] = None
    snapshots = frames["portfolio_snapshots"]
    snapshots.loc[
        (snapshots.event_time >= ACCRUAL) & (snapshots.event_time < PAYMENT), "cash_value_units"
    ] += 10
    tables, summary = _reconstruct(_manifest(), frames)
    assert tables["period_reconciliation.csv"].corporate_income.tolist() == [0, 10, 0, 0]
    assert tables["period_reconciliation.csv"].dividend_receivable.eq(0).all()
    assert summary["entitlements_checked"] == 0


def test_terminal_cash_redemption_is_trading_pnl_not_a_dividend():
    frames = _frames()
    ledger = frames["cash_ledger"]
    frames["cash_ledger"] = ledger[~ledger.reference_id.eq("fee-sell")].copy()
    frames["cash_ledger"].loc[frames["cash_ledger"].reference_id.eq("sell"), "event_type"] = (
        "corporate_action"
    )
    frames["fills"] = frames["fills"].iloc[:1]
    frames["costs"] = frames["costs"].iloc[:1]
    snapshots = frames["portfolio_snapshots"]
    snapshots.loc[snapshots.event_time >= SALE, ["cash_value_units", "nav_units"]] += 2
    _refresh_returns(frames)
    tables, _ = _reconstruct(_manifest(), frames)
    assert tables["period_reconciliation.csv"].net_pnl.tolist() == [9, 20, 4, 0]
    assert tables["period_reconciliation.csv"].corporate_income.tolist() == [0, 10, 0, 0]


def test_fee_rebate_keeps_native_type_and_positive_cash_effect():
    frames = _frames()
    ledger = frames["cash_ledger"]
    ledger.loc[ledger.reference_id.eq("fee-sell"), "amount_units"] *= -1
    frames["costs"].loc[1, "amount_units"] = -2
    snapshots = frames["portfolio_snapshots"]
    snapshots.loc[snapshots.event_time >= SALE, ["cash_value_units", "nav_units"]] += 4
    _refresh_returns(frames)
    tables, _ = _reconstruct(_manifest(), frames)
    assert tables["period_reconciliation.csv"].fee_cash.tolist() == [-1, 0, 2, 0]
    assert tables["fee_details.csv"].amount.tolist() == [1, -2]


def test_cash_only_run_can_publish_empty_security_and_fee_tables(tmp_path):
    frames = _frames()
    for name in ("positions", "fills", "costs", "orders", "order_events"):
        frames[name] = frames[name].iloc[:0]
    frames["cash_ledger"] = frames["cash_ledger"].iloc[:2]
    snapshots = frames["portfolio_snapshots"]
    snapshots["cash_value_units"] = snapshots["nav_units"] = 1000
    snapshots["market_value_units"] = 0
    frames["returns"]["nav_units"] = 1000
    frames["returns"]["net_return"] = 0.0
    source = tmp_path / "source"
    _write(source, frames)
    assert (
        main(["cash-attribution", "--run-dir", str(source), "--out-dir", str(tmp_path / "report")])
        == 0
    )
    assert pd.read_csv(tmp_path / "report/instrument_pnl.csv").empty
    assert pd.read_csv(tmp_path / "report/fee_details.csv").empty


def test_two_instruments_reconcile_separately_and_to_portfolio():
    frames = _frames()
    for name in ("positions", "fills", "costs", "cash_ledger"):
        original = frames[name]
        if name == "cash_ledger":
            original.loc[original.reference_id.eq("opening:CNY"), "amount_units"] *= 2
            extra = original[~original.reference_id.eq("opening:CNY")].copy()
        else:
            extra = original.copy()
        for column in (
            "transaction_id",
            "idempotency_key",
            "reference_id",
            "fill_id",
            "cost_id",
            "order_id",
            "instrument_id",
        ):
            if column in extra:
                extra[column] = extra[column].map(
                    lambda value: None if pd.isna(value) else value + "-second"
                )
        frames[name] = pd.concat([original, extra], ignore_index=True)
    for column in ("nav_units", "cash_value_units", "market_value_units"):
        frames["portfolio_snapshots"][column] *= 2
    frames["returns"]["nav_units"] *= 2
    tables, _ = _reconstruct(_manifest(), frames)
    pnl = tables["instrument_pnl.csv"]
    assert set(pnl.instrument_id) == {INSTRUMENT, INSTRUMENT + "-second"}
    assert pnl.groupby("instrument_id").net_pnl.sum().tolist() == [31, 31]
    assert tables["period_reconciliation.csv"].net_pnl.sum() == 62


def test_large_fixed_point_amounts_never_round_through_float():
    frames = _frames()
    multiplier = 10**11
    for frame in frames.values():
        for column in frame:
            if column.endswith("_units") and "quantity" not in column and column != "fx_rate_units":
                frame[column] *= multiplier
    tables, _ = _reconstruct(_manifest(), frames)
    assert tables["period_reconciliation.csv"].net_pnl.sum() == Decimal(31) * multiplier


@pytest.mark.parametrize("kind", ["funding", "settlement", "unknown"])
def test_unsupported_events_are_never_absorbed_into_residual(kind):
    frames = _frames()
    frames["cash_ledger"].loc[frames["cash_ledger"].reference_id.eq("payment"), "event_type"] = kind
    with pytest.raises(ValueError, match="不支持账本事件"):
        _reconstruct(_manifest(), frames)


def test_duplicate_rows_and_unmatched_quantities_rejected():
    frames = _frames()
    frames["fills"] = pd.concat([frames["fills"], frames["fills"].iloc[:1]])
    with pytest.raises(ValueError, match="fill_id重复"):
        _reconstruct(_manifest(), frames)
    frames = _frames()
    qty = frames["cash_ledger"].reference_id.eq("split")
    frames["cash_ledger"].loc[qty, "quantity_delta_units"] *= 2
    with pytest.raises(ValueError, match="数量与完整账本"):
        _reconstruct(_manifest(), frames)
