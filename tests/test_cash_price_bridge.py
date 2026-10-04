from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from test_cash_attribution import INSTRUMENT, SALE, SPLIT, T0, _frames, _write

from quant_report_hub import cash_price_bridge as bridge
from quant_report_hub.cash_attribution import reconcile_cash_ledger_v2
from quant_report_hub.cli import main
from quant_report_hub.execution_references import (
    QUOTE_COLUMNS,
    digest,
    fingerprint,
    load_references,
)


def _quote(identifier, stamp, midpoint):
    units = int(Decimal(midpoint) * 1000)
    return dict(
        zip(
            QUOTE_COLUMNS,
            (
                identifier,
                INSTRUMENT,
                "CNY",
                (stamp - pd.Timedelta(seconds=1)).isoformat(),
                (stamp - pd.Timedelta(milliseconds=500)).isoformat(),
                units - 1,
                3,
                units + 1,
                3,
                1,
                0,
            ),
        )
    )


def _package(root, run, *, quotes=None, kind="synthetic"):
    root.mkdir()
    pd.DataFrame(
        quotes
        if quotes is not None
        else [_quote("buy-quote", T0, "9.9"), _quote("sell-quote", SALE, "6.1")],
        columns=QUOTE_COLUMNS,
    ).to_csv(root / "quotes.csv", index=False, lineterminator="\n")
    value = {
        "schema_version": "quant-report-hub.execution-references/v1",
        "source_run_manifest_sha256": digest((run / "standard/v2/run_manifest.json").read_bytes()),
        "source": {
            "evidence_kind": kind,
            "provider": "synthetic fixture",
            "dataset_id": "cash-hand-check-v1",
            "description": "手算报价，仅验证软件。",
        },
        "policy": {
            "clock": "first_order_acceptance",
            "price": "last_available_midquote",
            "price_basis": "unadjusted_trade_currency",
            "max_quote_age_ms": 1000,
        },
        "quotes": {"path": "quotes.csv", "sha256": digest((root / "quotes.csv").read_bytes())},
    }
    return _save(root / "references.json", value)


def _save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
    return path, digest(path.read_bytes())


def _inputs(tmp_path, *, frames=None, quotes=None, kind="synthetic"):
    source = tmp_path / "source"
    _write(source, _frames() if frames is None else frames)
    ref, sha = _package(tmp_path / "quotes", source, quotes=quotes, kind=kind)
    return source, ref, sha


def _run(source, ref, sha, out):
    return bridge.write_cash_price_bridge(
        source, references=ref, references_sha256=sha, out_dir=out
    )


def _csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_signed_buy_sell_bridge_preserves_native_tables_and_sources(tmp_path):
    source, ref, sha = _inputs(tmp_path)
    before = fingerprint([*source.rglob("*.*"), *ref.parent.iterdir()])
    out = tmp_path / "report"
    result = _run(source, ref, sha, out)
    expected = {
        "net_pnl": "31.00",
        "execution_price_pnl": "1.00",
        "reference_price_valuation_pnl": "23.00",
        "favorable_pnl": "2.00",
        "adverse_pnl": "-1.00",
        "bridge_residual": "0",
    }
    assert {name: result["summary"][name] for name in expected} == expected
    fills = _csv(out / "fill_price_bridge.csv")
    assert fills.quote_id.tolist() == ["buy-quote", "sell-quote"]
    assert list(map(Decimal, fills.execution_price_pnl)) == [Decimal(-1), Decimal(2)]
    periods = _csv(out / "period_price_bridge.csv")
    assert list(map(Decimal, periods.net_pnl)) == [9, 20, 2, 0]
    assert list(map(Decimal, periods.reference_price_valuation_pnl)) == [11, 10, 2, 0]
    assert all(Decimal(v) == 0 for v in periods.bridge_residual)
    original = tmp_path / "cash-only-report"
    baseline = reconcile_cash_ledger_v2(source, out_dir=original)
    for name in baseline["row_counts"]:
        assert (original / name).read_bytes() == (out / name).read_bytes()
    verified = bridge.verify_cash_price_bridge(
        source,
        references=ref,
        references_sha256=sha,
        report_dir=out,
        manifest_sha256=digest((out / "manifest.json").read_bytes()),
    )
    assert verified == result
    assert fingerprint(before) == before
    page = (out / "report.html").read_text(encoding="utf-8")
    assert "合成报价·软件验证" in page and "不是重新回测" in page
    assert str(tmp_path) not in (out / "manifest.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("buy,sell,expected", [("10.1", "6.3", [1, -2]), ("10", "6.2", [0, 0])])
def test_opposite_signs_and_zero_price_difference(tmp_path, buy, sell, expected):
    source, ref, sha = _inputs(tmp_path, quotes=[_quote("b", T0, buy), _quote("s", SALE, sell)])
    _run(source, ref, sha, tmp_path / "out")
    assert (
        list(map(Decimal, _csv(tmp_path / "out/fill_price_bridge.csv").execution_price_pnl))
        == expected
    )


def test_midpoint_and_native_cash_rounding_are_separate(tmp_path):
    quotes = [_quote("b", T0, "10"), _quote("s", SALE, "6.2")]
    quotes[0].update(bid_price_units=9999, ask_price_units=10000)
    source, ref, sha = _inputs(tmp_path, quotes=quotes)
    _run(source, ref, sha, tmp_path / "out")
    row = _csv(tmp_path / "out/fill_price_bridge.csv").iloc[0]
    assert Decimal(row.reference_price) == Decimal("9.9995")
    assert Decimal(row.raw_adverse_cost) == Decimal("0.005")
    assert Decimal(row.reference_trade_cash) == Decimal("-100.00")
    assert Decimal(row.execution_price_pnl) == 0
    assert Decimal(row.rounding_pnl) == Decimal("0.005")


def test_later_available_quote_is_not_used_and_latest_eligible_is_selected(tmp_path):
    quotes = [
        _quote("old", T0 - pd.Timedelta(milliseconds=100), "9"),
        _quote("latest", T0, "9.9"),
        _quote("future", T0 + pd.Timedelta(seconds=1), "50"),
        _quote("sell", SALE, "6.1"),
    ]
    source, ref, sha = _inputs(tmp_path, quotes=quotes)
    _run(source, ref, sha, tmp_path / "out")
    assert _csv(tmp_path / "out/fill_price_bridge.csv").quote_id.tolist() == ["latest", "sell"]


def test_partial_fills_use_same_order_acceptance_quote(tmp_path):
    frames = _frames()
    first = frames["fills"].iloc[0].copy()
    second = first.copy()
    first["fill_id"], first["quantity_units"] = "buy-a", 4
    second["fill_id"], second["quantity_units"] = "buy-b", 6
    frames["fills"] = pd.concat(
        [pd.DataFrame([first, second]), frames["fills"].iloc[1:]], ignore_index=True
    )
    frames["costs"].loc[0, "fill_id"] = "buy-a"
    ledger = frames["cash_ledger"]
    split = ledger[ledger.reference_id.eq("buy")].copy()
    pieces = []
    for suffix, quantity in (("a", 4), ("b", 6)):
        part = split.copy()
        for field in ("transaction_id", "idempotency_key", "reference_id"):
            part[field] = "buy-" + suffix
        part["amount_units"] = part["amount_units"] // 10 * quantity
        part["quantity_delta_units"] = part["quantity_delta_units"] // 10 * quantity
        pieces.append(part)
    frames["cash_ledger"] = pd.concat(
        [ledger[~ledger.reference_id.eq("buy")], *pieces], ignore_index=True
    )
    events = frames["order_events"]
    partial = events.iloc[1].copy()
    partial["to_status"], partial["fill_quantity_units"] = "partially_filled", 4
    final = partial.copy()
    (
        final["event_id"],
        final["event_sequence"],
        final["from_status"],
        final["to_status"],
        final["fill_quantity_units"],
    ) = "buy-3", 3, "partially_filled", "filled", 6
    frames["order_events"] = pd.concat(
        [events.iloc[:1], pd.DataFrame([partial, final]), events.iloc[2:]], ignore_index=True
    )
    frames["orders"].loc[0, "version"] = 3
    source, ref, sha = _inputs(tmp_path, frames=frames)
    result = _run(source, ref, sha, tmp_path / "out")
    fills = _csv(tmp_path / "out/fill_price_bridge.csv")
    assert fills.fill_id.tolist() == ["buy-a", "buy-b", "sell"]
    assert fills.quote_id.tolist() == ["buy-quote", "buy-quote", "sell-quote"]
    assert list(map(Decimal, fills.execution_price_pnl)) == [
        Decimal("-0.4"),
        Decimal("-0.6"),
        Decimal(2),
    ]
    assert Decimal(result["summary"]["net_pnl"]) == 31


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("currency", "USD", "缺少已可得报价"),
        ("instrument_id", "other", "缺少已可得报价"),
        ("available_at", (T0 + pd.Timedelta(seconds=1)).isoformat(), "缺少已可得报价"),
        ("observed_at", (T0 - pd.Timedelta(seconds=2)).isoformat(), "过期"),
        ("observed_at", T0.isoformat(), "早于observed_at"),
        ("available_at", "2025-01-02T07:00:00", "UTC"),
        ("quote_id", "", "非空"),
        ("bid_price_units", "0", "报价须为正"),
        ("ask_price_units", "1", "买价不高于"),
        ("multiplier_units", "2", "单位乘数"),
        ("bid_price_scale", "19", "scale"),
        ("bid_price_units", "NaN", "整数"),
        ("bid_price_units", "9.9", "整数"),
        ("bid_price_units", str(2**63), "64位整数"),
    ],
)
def test_invalid_or_noncausal_quotes_block_publication(tmp_path, field, value, message):
    quotes = [_quote("b", T0, "9.9"), _quote("s", SALE, "6.1")]
    quotes[0][field] = value
    source, ref, sha = _inputs(tmp_path, quotes=quotes)
    with pytest.raises(ValueError, match=message):
        _run(source, ref, sha, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("duplicate_clock", [False, True])
def test_ambiguous_quote_identity_is_rejected(tmp_path, duplicate_clock):
    quote = _quote("b", T0, "9.9")
    extra = {**quote, "quote_id": "other"} if duplicate_clock else dict(quote)
    source, ref, sha = _inputs(tmp_path, quotes=[quote, extra])
    with pytest.raises(ValueError, match="歧义|重复"):
        _run(source, ref, sha, tmp_path / "out")


@pytest.mark.parametrize(
    "section,field,value",
    [
        (None, "schema_version", "unknown"),
        (None, "source_run_manifest_sha256", "f" * 64),
        (None, "extra", True),
        ("source", "evidence_kind", "real"),
        ("source", "provider", ""),
        ("policy", "clock", "fill_time"),
        ("policy", "price", "last_trade"),
        ("policy", "price_basis", "adjusted"),
        ("policy", "max_quote_age_ms", True),
        ("policy", "max_quote_age_ms", -1),
        ("policy", "max_quote_age_ms", 86400001),
        ("quotes", "path", "../quotes.csv"),
        ("quotes", "sha256", "0" * 64),
    ],
)
def test_reference_contract_is_closed_and_bound(tmp_path, section, field, value):
    source, ref, sha = _inputs(tmp_path)
    data = json.loads(ref.read_bytes())
    (data if section is None else data[section])[field] = value
    ref, sha = _save(ref, data)
    with pytest.raises(ValueError):
        _run(source, ref, sha, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "kind,label",
    [("model", "模型报价·假设分析"), ("independently_observed", "独立观察报价·提供者声明")],
)
def test_source_claims_are_labels_not_market_certification(tmp_path, kind, label):
    source, ref, sha = _inputs(tmp_path, kind=kind)
    metadata = json.loads(ref.read_bytes())
    metadata["source"]["provider"] = '<script>alert("x")</script>'
    ref, sha = _save(ref, metadata)
    result = _run(source, ref, sha, tmp_path / "out")
    page = (tmp_path / "out/report.html").read_text(encoding="utf-8")
    assert label in page and "&lt;script&gt;" in page and "<script>" not in page
    assert "market_data_certified" not in result


def test_duplicate_json_keys_wrong_hash_and_changed_quotes_rejected(tmp_path):
    source, ref, sha = _inputs(tmp_path)
    with pytest.raises(ValueError, match="清单SHA"):
        _run(source, ref, "f" * 64, tmp_path / "out")
    original = ref.read_bytes()
    ref.write_bytes(b'{"schema_version":"duplicate",' + original[1:])
    with pytest.raises(ValueError, match="JSON字段重复"):
        _run(source, ref, digest(ref.read_bytes()), tmp_path / "out")
    ref.write_bytes(original)
    (ref.parent / "quotes.csv").write_bytes(b"modified")
    with pytest.raises(ValueError, match="报价文件SHA"):
        _run(source, ref, sha, tmp_path / "out")


def test_missing_quotes_bad_columns_and_missing_file_rejected(tmp_path):
    source, ref, sha = _inputs(tmp_path, quotes=[])
    with pytest.raises(ValueError, match="缺少已可得报价"):
        _run(source, ref, sha, tmp_path / "out")
    csv = ref.parent / "quotes.csv"
    csv.write_text("unexpected\n1\n", encoding="utf-8")
    metadata = json.loads(ref.read_bytes())
    metadata["quotes"]["sha256"] = digest(csv.read_bytes())
    ref, sha = _save(ref, metadata)
    with pytest.raises(ValueError, match="CSV字段"):
        _run(source, ref, sha, tmp_path / "out")
    csv.unlink()
    with pytest.raises(ValueError, match="普通文件"):
        _run(source, ref, sha, tmp_path / "out")


@pytest.mark.parametrize("field", ["account_id", "strategy_id", "instrument_id", "side"])
def test_order_fill_identity_mismatch_rejected(tmp_path, field):
    source, ref, sha = _inputs(tmp_path)
    _, quotes, _ = load_references(
        ref, sha, digest((source / "standard/v2/run_manifest.json").read_bytes())
    )
    frames = _frames()
    frames["orders"].loc[0, field] = "sell" if field == "side" else "other"
    with pytest.raises(ValueError, match=f"成交与订单{field}不一致"):
        bridge._fills(
            frames,
            quotes,
            {"max_quote_age_ms": 1000},
            {"account_id": "account", "strategy_id": "strategy"},
            [SALE],
        )


def test_delayed_acceptance_and_missing_acceptance_rejected(tmp_path):
    source, ref, sha = _inputs(tmp_path)
    _, quotes, _ = load_references(
        ref, sha, digest((source / "standard/v2/run_manifest.json").read_bytes())
    )
    frames = _frames()
    summary = {"account_id": "account", "strategy_id": "strategy"}
    policy = {"max_quote_age_ms": 1000}
    frames["order_events"].loc[0, "event_time"] = T0 + pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="早于订单接受"):
        bridge._fills(frames, quotes, policy, summary, [SALE])
    frames["order_events"] = frames["order_events"].iloc[1:]
    with pytest.raises(ValueError, match="唯一原生订单"):
        bridge._fills(frames, quotes, policy, summary, [SALE])


def test_quote_crossing_corporate_action_is_rejected(tmp_path):
    source, ref, sha = _inputs(tmp_path)
    metadata = json.loads(ref.read_bytes())
    metadata["policy"]["max_quote_age_ms"] = 86400000
    quotes = [_quote("b", T0, "9.9"), _quote("s", SALE, "6.1")]
    quotes[1]["observed_at"] = SPLIT.isoformat()
    quotes[1]["available_at"] = SPLIT.isoformat()
    pd.DataFrame(quotes, columns=QUOTE_COLUMNS).to_csv(ref.parent / "quotes.csv", index=False)
    metadata["quotes"]["sha256"] = digest((ref.parent / "quotes.csv").read_bytes())
    ref, sha = _save(ref, metadata)
    with pytest.raises(ValueError, match="跨公司行动"):
        _run(source, ref, sha, tmp_path / "out")


def test_cash_only_run_has_no_execution_quality_claim(tmp_path):
    frames = _frames()
    for name in ("positions", "fills", "costs", "orders", "order_events"):
        frames[name] = frames[name].iloc[:0]
    frames["cash_ledger"] = frames["cash_ledger"].iloc[:2]
    frames["portfolio_snapshots"]["cash_value_units"] = 1000
    frames["portfolio_snapshots"]["nav_units"] = 1000
    frames["portfolio_snapshots"]["market_value_units"] = 0
    frames["returns"]["nav_units"] = 1000
    frames["returns"]["net_return"] = 0.0
    source, ref, sha = _inputs(tmp_path, frames=frames, quotes=[])
    receipt = _run(source, ref, sha, tmp_path / "out")
    assert receipt["summary"]["fills_checked"] == 0
    assert Decimal(receipt["summary"]["execution_price_pnl"]) == 0
    assert _csv(tmp_path / "out/instrument_price_bridge.csv").empty
    assert "不产生执行质量结论" in (tmp_path / "out/report.html").read_text(encoding="utf-8")


def test_two_instruments_are_reconciled_individually(tmp_path):
    frames = _frames()
    for name in ("positions", "fills", "costs", "cash_ledger", "orders", "order_events"):
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
            "event_id",
        ):
            if column in extra:
                extra[column] = extra[column].map(
                    lambda value: None if pd.isna(value) else value + "-second"
                )
        frames[name] = pd.concat([original, extra], ignore_index=True)
    for column in ("nav_units", "cash_value_units", "market_value_units"):
        frames["portfolio_snapshots"][column] *= 2
    frames["returns"]["nav_units"] *= 2
    quotes = [_quote("buy", T0, "9.9"), _quote("sell", SALE, "6.1")]
    quotes += [
        {**q, "quote_id": q["quote_id"] + "-second", "instrument_id": INSTRUMENT + "-second"}
        for q in quotes
    ]
    source, ref, sha = _inputs(tmp_path, frames=frames, quotes=quotes)
    receipt = _run(source, ref, sha, tmp_path / "out")
    assert Decimal(receipt["summary"]["net_pnl"]) == 62
    assert Decimal(receipt["summary"]["execution_price_pnl"]) == 2
    frame = _csv(tmp_path / "out/instrument_price_bridge.csv")
    for instrument in (INSTRUMENT, INSTRUMENT + "-second"):
        assert sum(map(Decimal, frame[frame.instrument_id.eq(instrument)].execution_price_pnl)) == 1


def test_rehashed_forged_report_does_not_pass_native_recomputation(tmp_path):
    source, ref, sha = _inputs(tmp_path)
    out = tmp_path / "out"
    _run(source, ref, sha, out)
    csv = out / "fill_price_bridge.csv"
    csv.write_bytes(csv.read_bytes().replace(b"-1.00", b"-9.00"))
    manifest = json.loads((out / "manifest.json").read_bytes())
    manifest["files"][csv.name] = digest(csv.read_bytes())
    _save(out / "manifest.json", manifest)
    with pytest.raises(ValueError, match="原生重算不一致"):
        bridge.verify_cash_price_bridge(
            source,
            references=ref,
            references_sha256=sha,
            report_dir=out,
            manifest_sha256=digest((out / "manifest.json").read_bytes()),
        )


@pytest.mark.parametrize("target", ["csv", "manifest", "extra", "missing"])
def test_verifier_recomputes_and_rejects_report_tampering(tmp_path, target):
    source, ref, sha = _inputs(tmp_path)
    out = tmp_path / "out"
    _run(source, ref, sha, out)
    manifest_hash = digest((out / "manifest.json").read_bytes())
    if target == "manifest":
        (out / "manifest.json").write_text("{}", encoding="utf-8")
    elif target == "missing":
        (out / "fill_price_bridge.csv").unlink()
    elif target == "extra":
        (out / "unverified.txt").write_text("extra", encoding="utf-8")
    else:
        (out / "fill_price_bridge.csv").write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError):
        bridge.verify_cash_price_bridge(
            source,
            references=ref,
            references_sha256=sha,
            report_dir=out,
            manifest_sha256=manifest_hash,
        )


@pytest.mark.parametrize("stage", ["computation", "publication"])
@pytest.mark.parametrize("changed", ["native", "quote"])
def test_source_changes_during_work_do_not_publish(tmp_path, monkeypatch, stage, changed):
    source, ref, sha = _inputs(tmp_path)
    path = (
        source / "standard/v2/returns.parquet" if changed == "native" else ref.parent / "quotes.csv"
    )
    if stage == "computation":
        original = bridge._render

        def mutate(*args, **kwargs):
            page = original(*args, **kwargs)
            path.write_bytes(path.read_bytes() + b" ")
            return page

        monkeypatch.setattr(bridge, "_render", mutate)
    else:
        original = Path.write_bytes

        def mutate(self, data):
            result = original(self, data)
            if self.name == "report.html":
                original(path, path.read_bytes() + b" ")
            return result

        monkeypatch.setattr(Path, "write_bytes", mutate)
    with pytest.raises(ValueError, match="来源在归因期间变化"):
        _run(source, ref, sha, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".cash-price-*"))


def test_cli_success_verify_failure_and_output_guards(tmp_path, capsys):
    source, ref, sha = _inputs(tmp_path)
    common = ["--run-dir", str(source), "--references", str(ref), "--references-sha256", sha]
    out = tmp_path / "out"
    assert main(["cash-price-bridge", *common, "--out-dir", str(out)]) == 0
    assert (
        main(
            [
                "verify-cash-price-bridge",
                *common,
                "--report-dir",
                str(out),
                "--manifest-sha256",
                digest((out / "manifest.json").read_bytes()),
            ]
        )
        == 0
    )
    assert main(["cash-price-bridge", *common, "--out-dir", str(out)]) == 1
    assert "拒绝覆盖" in capsys.readouterr().err
    for path in (source, source / "nested", ref.parent / "nested"):
        with pytest.raises(ValueError, match="来源目录之外"):
            _run(source, ref, sha, path)
    assert (
        main(
            [
                "cash-price-bridge",
                *common,
                "--out-dir",
                str(tmp_path / "new"),
                "--references",
                str(tmp_path / "missing"),
            ]
        )
        == 1
    )


def test_original_accounting_failure_still_blocks_bridge(tmp_path):
    frames = _frames()
    frames["returns"].loc[0, "net_return"] = 0
    source, ref, sha = _inputs(tmp_path, frames=frames)
    with pytest.raises(ValueError, match="净收益率"):
        _run(source, ref, sha, tmp_path / "out")
