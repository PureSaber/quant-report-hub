import copy
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

import pandas as pd
import pytest
from test_cash_attribution import _frames, _write
from test_v2_attribution import _references, _source_row, _write_run

from quant_report_hub.portfolio_attribution import evaluate_portfolio_attribution, main, run_report


def account(identity, asset_class="equity", currency="USD", evidence="reported_components"):
    return {
        "id": identity,
        "economic_scope": identity,
        "asset_class": asset_class,
        "currency": currency,
        "evidence_level": evidence,
        "source_ref": "synthetic:test",
        "data_nature": "synthetic",
        "periods": [],
    }


def period(opening="100", closing="110", fx0="1", fx1="1", components=None):
    return {
        "start": "2025-01-01T00:00:00Z",
        "end": "2025-01-02T00:00:00Z",
        "known_at": "2025-01-02T00:00:00Z",
        "opening_nav": opening,
        "closing_nav": closing,
        "fx_start": fx0,
        "fx_end": fx1,
        "fx_start_known_at": "2025-01-01T00:00:00Z",
        "fx_end_known_at": "2025-01-02T00:00:00Z",
        "flows": [],
        "components": {} if components is None else components,
    }


def flow(amount="20", fx="1.2", kind="external", transfer="t1"):
    return {
        "flow_id": "flow-" + amount,
        "amount": amount,
        "fx_rate": fx,
        "kind": kind,
        "transfer_id": transfer,
        "time": "2025-01-01T12:00:00Z",
        "known_at": "2025-01-01T12:00:00Z",
        "fx_known_at": "2025-01-01T12:00:00Z",
    }


def portfolio():
    a = account("eur-equity", currency="EUR")
    a["periods"] = [period("100", "130", "1.1", "1.3", {"price": "8", "dividend": "1"})]
    a["periods"][0]["flows"] = [flow()]
    b = account("usd-cash", asset_class="cash")
    b["periods"] = [period("50", "51", components={"cash_interest": "1"})]
    c = account("fund-nav", asset_class="fund", evidence="nav_bridge")
    c["periods"] = [period("20", "19")]
    return {
        "schema": "quant-report-hub.portfolio-attribution/v1",
        "base_currency": "USD",
        "evaluation_as_of": "2025-01-10T00:00:00Z",
        "accounts": [a, b, c],
        "risk_models": [
            {
                "period_start": "2025-01-01T00:00:00Z",
                "estimation_end": "2024-12-31T00:00:00Z",
                "known_at": "2025-01-01T00:00:00Z",
                "source_ref": "synthetic:covariance",
                "period_unit": "one day",
                "return_basis": "base_net_simple_total_return",
                "accounts": ["eur-equity", "usd-cash", "fund-nav"],
                "covariance": [[0.01, 0, 0.001], [0, 0, 0], [0.001, 0, 0.0025]],
            }
        ],
    }


def test_fx_flows_cash_residual_independent_amounts_and_euler_variance():
    out = evaluate_portfolio_attribution(portfolio())
    a, b, c = out["accounts"]
    # EUR P&L 130-100-20=10; translated 13. Opening FX 20; flow FX 2. Total 35 USD.
    assert D(a["pnl_base"]) == 35
    assert a["components_base"] == {
        "price": "10.4",
        "dividend": "1.3",
        "residual": "1.3",
        "fx_on_opening_nav": "20.0",
        "fx_on_flows": "2.0",
    }
    assert b["components_base"]["cash_interest"] == "1"
    assert c["local_residual"] == "-1" and c["evidence_level"] == "nav_bridge"
    total = out["portfolio"][0]
    assert D(total["opening_base"]) == 180 and D(total["closing_base"]) == 239
    assert D(total["external_flow_base"]) == 24 and D(total["pnl_base"]) == 35
    assert sum(D(v) for v in total["components_base"].values()) == 35
    assert total["return_interpretation"] == "flow_affected_ratio_not_TWR"
    risk = total["risk_attribution"]
    w1, w3 = 110 / 180, 20 / 180
    independent = w1**2 * 0.01 + w3**2 * 0.0025 + 2 * w1 * w3 * 0.001
    assert risk["variance"] == pytest.approx(independent)
    assert sum(risk["variance_contributions"].values()) == pytest.approx(independent)
    assert sum(risk["volatility_contributions"].values()) == pytest.approx(independent**0.5)


def test_internal_transfer_netting_no_double_count_and_zero_net_flow_not_twr():
    spec = portfolio()
    spec["accounts"][0]["periods"][0]["flows"][0]["kind"] = "internal_transfer"
    spec["accounts"][1]["periods"][0]["flows"] = [flow("-24", "1", "internal_transfer")]
    spec["accounts"][1]["periods"][0]["closing_nav"] = "27"
    total = evaluate_portfolio_attribution(spec)["portfolio"][0]
    assert total["external_flow_base"] == "0"
    assert D(total["closing_base"]) == 215 and D(total["pnl_base"]) == 35
    spec["accounts"][1]["periods"][0]["flows"][0]["amount"] = "-23"
    with pytest.raises(ValueError, match="pair"):
        evaluate_portfolio_attribution(spec)
    spec = portfolio()
    spec["accounts"] = [spec["accounts"][1]]
    spec["risk_models"] = []
    spec["accounts"][0]["periods"][0]["flows"] = [flow("5", "1"), flow("-5", "1")]
    assert evaluate_portfolio_attribution(spec)["portfolio"][0]["return_interpretation"].startswith(
        "flow"
    )
    spec["accounts"][0]["periods"][0]["flows"] = [flow("5", "1"), flow("5", "1")]
    with pytest.raises(ValueError, match="duplicate flow"):
        evaluate_portfolio_attribution(spec)


def test_native_adapter_rebuilds_source_and_rejects_mutation(tmp_path):
    run = tmp_path / "source"
    frames = _frames()
    _write(run, frames)
    a = account("native-cash", currency="CNY", evidence="native_cash_ledger")
    a.update(
        run_dir="source",
        run_manifest_sha256=hashlib.sha256(
            (run / "standard/v2/run_manifest.json").read_bytes()
        ).hexdigest(),
    )
    last = pd.Timestamp("2025-01-01T00:00:00Z")
    for end in frames["returns"].event_time:
        row = period()
        row.update(
            start=last.isoformat(),
            end=end.isoformat(),
            known_at="2025-01-09T00:00:00Z",
            fx_start_known_at=last.isoformat(),
            fx_end_known_at=end.isoformat(),
        )
        a["periods"].append(row)
        last = end
    spec = dict(portfolio(), base_currency="CNY", accounts=[a], risk_models=[])
    out = evaluate_portfolio_attribution(spec, source_root=tmp_path)
    assert [D(r["pnl_base"]) for r in out["accounts"]] == [9, 20, 2, 0]
    assert all(D(r["local_residual"]) == 0 for r in out["accounts"])
    assert out["sources"]["native-cash"]["summary"]["transactions_checked"] == 8
    # Adapter ignores fabricated caller NAV/components and derives the ledger numbers.
    assert D(out["accounts"][0]["opening_base"]) == 1000
    for key, value, match in [
        ("run_manifest_sha256", "0" * 64, "hash"),
        ("currency", "USD", "currency"),
    ]:
        bad = copy.deepcopy(spec)
        bad["accounts"][0][key] = value
        with pytest.raises(ValueError, match=match):
            evaluate_portfolio_attribution(bad, source_root=tmp_path)
    second = copy.deepcopy(a)
    second.update(id="duplicate", economic_scope="duplicate")
    with pytest.raises(ValueError, match="duplicate native"):
        evaluate_portfolio_attribution(dict(spec, accounts=[a, second]), source_root=tmp_path)
    for change in [
        lambda x: x["periods"].pop(),
        lambda x: x["periods"][0].update(end="2025-01-03T00:00:00Z"),
        lambda x: x["periods"][0].update(known_at="2025-01-03T00:00:00Z"),
        lambda x: x["periods"][0].update(start="2025-01-02T08:00:00Z"),
    ]:
        bad = copy.deepcopy(spec)
        change(bad["accounts"][0])
        with pytest.raises(ValueError):
            evaluate_portfolio_attribution(bad, source_root=tmp_path)
    source = tmp_path / "native.json"
    source.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="outside native"):
        run_report(source, run / "report")
    (run / "standard/v2/returns.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        evaluate_portfolio_attribution(spec, source_root=tmp_path)


def test_v2_futures_crypto_components_reuse_original_checks(tmp_path):
    run = tmp_path / "futures"
    _write_run(
        run,
        source=[_source_row("price", 20), _source_row("carry", 5), _source_row("roll", -4)],
        costs=[("commission", 2, None)],
        nav_delta=19,
    )
    a = account("futures", asset_class="future", evidence="validated_v2_components")
    a.update(
        run_dir="futures",
        run_manifest_sha256=hashlib.sha256(
            (run / "standard/v2/run_manifest.json").read_bytes()
        ).hexdigest(),
    )
    row = period()
    row.update(
        start="2025-01-02T00:00:00Z",
        end="2025-01-03T00:00:00Z",
        known_at="2025-01-05T00:00:00Z",
        fx_start_known_at="2025-01-02T00:00:00Z",
        fx_end_known_at="2025-01-03T00:00:00Z",
    )
    a["periods"] = [row]
    spec = dict(portfolio(), accounts=[a], risk_models=[])
    out = evaluate_portfolio_attribution(spec, source_root=tmp_path)
    parts = out["accounts"][0]["components_base"]
    assert {k: D(parts[k]) for k in ("price", "carry", "roll", "commission", "residual")} == {
        "price": 20,
        "carry": 5,
        "roll": -4,
        "commission": -2,
        "residual": 0,
    }
    assert D(out["portfolio"][0]["pnl_base"]) == 19
    for change in [
        lambda x: x.update(run_manifest_sha256="0" * 64),
        lambda x: x.update(periods=[]),
        lambda x: x["periods"][0].update(known_at="2025-01-03T00:00:00Z"),
    ]:
        broken = copy.deepcopy(spec)
        change(broken["accounts"][0])
        with pytest.raises(ValueError):
            evaluate_portfolio_attribution(broken, source_root=tmp_path)
    references = tmp_path / "refs.csv"
    _references().to_csv(references, index=False)
    a.update(
        slippage_references="refs.csv",
        slippage_references_sha256=hashlib.sha256(references.read_bytes()).hexdigest(),
    )
    with pytest.raises(ValueError, match="slippage"):
        evaluate_portfolio_attribution(spec, source_root=tmp_path)
    a["slippage_references_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="reference hash"):
        evaluate_portfolio_attribution(spec, source_root=tmp_path)
    crypto = tmp_path / "crypto"
    _write_run(
        crypto,
        source=[_source_row("price", 20), _source_row("fx", 5)],
        costs=[
            ("maker_fee", 1, "fill-1"),
            ("taker_fee", 1, "fill-1"),
            ("funding", 2, None),
            ("slippage", 1, "fill-1"),
        ],
        nav_delta=20,
    )
    a.update(
        run_dir="crypto",
        asset_class="crypto",
        run_manifest_sha256=hashlib.sha256(
            (crypto / "standard/v2/run_manifest.json").read_bytes()
        ).hexdigest(),
        slippage_references_sha256=hashlib.sha256(references.read_bytes()).hexdigest(),
    )
    crypto_result = evaluate_portfolio_attribution(spec, source_root=tmp_path)
    assert D(crypto_result["portfolio"][0]["pnl_base"]) == 20
    assert D(crypto_result["accounts"][0]["components_base"]["funding"]) == -2
    assert D(crypto_result["accounts"][0]["components_base"]["fx"]) == 5


@pytest.mark.parametrize("pinned_valid", [False, True])
def test_v2_slippage_uses_the_hashed_snapshot_after_source_replacement(
    tmp_path, monkeypatch, pinned_valid
):
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
    valid = _references().to_csv(index=False).encode("utf-8")
    invalid_frame = _references()
    invalid_frame.loc[0, "reference_price_units"] = 90
    invalid = invalid_frame.to_csv(index=False).encode("utf-8")
    pinned, replacement = (valid, invalid) if pinned_valid else (invalid, valid)
    reference = tmp_path / "refs.csv"
    reference.write_bytes(pinned)
    a = account("crypto", asset_class="crypto", evidence="validated_v2_components")
    a.update(
        run_dir="crypto",
        run_manifest_sha256=hashlib.sha256(
            (run / "standard/v2/run_manifest.json").read_bytes()
        ).hexdigest(),
        slippage_references="refs.csv",
        slippage_references_sha256=hashlib.sha256(pinned).hexdigest(),
    )
    row = period()
    row.update(
        start="2025-01-02T00:00:00Z",
        end="2025-01-03T00:00:00Z",
        known_at="2025-01-05T00:00:00Z",
        fx_start_known_at="2025-01-02T00:00:00Z",
        fx_end_known_at="2025-01-03T00:00:00Z",
    )
    a["periods"] = [row]
    spec = dict(portfolio(), accounts=[a], risk_models=[])
    read_bytes = Path.read_bytes
    reads = []

    def replace_after_read(path):
        raw = read_bytes(path)
        if path.resolve() == reference.resolve():
            reads.append(raw)
            reference.write_bytes(replacement)
        return raw

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    if pinned_valid:
        result = evaluate_portfolio_attribution(spec, source_root=tmp_path)
        assert D(result["portfolio"][0]["pnl_base"]) == 20
        assert D(result["accounts"][0]["components_base"]["slippage"]) == -1
    else:
        with pytest.raises(ValueError, match="slippage.*reference/fill"):
            evaluate_portfolio_attribution(spec, source_root=tmp_path)
    assert reads == [pinned]
    assert read_bytes(reference) == replacement


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(schema="bad"),
        lambda s: s.update(evaluation_as_of="2025-01-01"),
        lambda s: s["accounts"].append(s["accounts"][0]),
        lambda s: s["accounts"][0].update(evidence_level="exact"),
        lambda s: s["accounts"][0].update(data_nature="live"),
        lambda s: s["accounts"][0].update(source_ref=""),
        lambda s: s["accounts"][0]["periods"][0].update(known_at="2025-02-01T00:00:00Z"),
        lambda s: s["accounts"][0]["periods"][0].update(fx_start="0"),
        lambda s: s["accounts"][0]["periods"][0].update(fx_start_known_at="2024-01-01T00:00:00Z"),
        lambda s: s["accounts"][0]["periods"][0].update(fx_end_known_at="2026-01-01T00:00:00Z"),
        lambda s: s["accounts"][1]["periods"][0].update(fx_end="2"),
        lambda s: s["accounts"][0]["periods"][0].update(opening_nav=100),
        lambda s: s["accounts"][0]["periods"][0].update(opening_nav="nan"),
        lambda s: s["accounts"][0]["periods"][0].update(opening_nav="bad"),
        lambda s: s["accounts"][0]["periods"][0]["components"].update(residual="0"),
        lambda s: s["accounts"][2]["periods"][0]["components"].update(price="1"),
        lambda s: s["accounts"][0]["periods"][0]["flows"][0].update(kind="dividend"),
        lambda s: s["accounts"][0]["periods"][0]["flows"][0].update(time="2026-01-01T00:00:00Z"),
        lambda s: s["accounts"][0]["periods"][0]["flows"][0].update(
            fx_known_at="2026-01-01T00:00:00Z"
        ),
        lambda s: s["accounts"][0].update(periods=[]),
        lambda s: s["accounts"][1]["periods"][0].update(start="2025-01-01T01:00:00Z"),
        lambda s: s["risk_models"].append(s["risk_models"][0]),
        lambda s: s["risk_models"][0].update(known_at="2025-01-02T00:00:00Z"),
        lambda s: s["risk_models"][0].update(accounts=[]),
        lambda s: s["risk_models"][0].update(covariance=[[1]]),
        lambda s: s["risk_models"][0].update(covariance=[[1, 2, 0], [2, 1, 0], [0, 0, 1]]),
    ],
)
def test_invalid_rejected(change):
    spec = portfolio()
    change(spec)
    with pytest.raises((ValueError, TypeError)):
        evaluate_portfolio_attribution(spec)


def test_continuity_unavailable_risk_and_publish_verify(tmp_path):
    spec = portfolio()
    for a in spec["accounts"]:
        later = copy.deepcopy(a["periods"][0])
        later.update(
            start="2025-01-02T00:00:00Z",
            end="2025-01-03T00:00:00Z",
            known_at="2025-01-03T00:00:00Z",
            fx_start_known_at="2025-01-02T00:00:00Z",
            fx_end_known_at="2025-01-03T00:00:00Z",
            opening_nav=later["closing_nav"],
            fx_start=later["fx_end"],
            flows=[],
            components={},
        )
        a["periods"].append(later)
    assert (
        evaluate_portfolio_attribution(spec)["portfolio"][1]["risk_attribution"]["status"]
        == "unavailable"
    )
    spec["accounts"][0]["periods"][1]["opening_nav"] = "9"
    with pytest.raises(ValueError, match="chain"):
        evaluate_portfolio_attribution(spec)
    spec = portfolio()
    spec["accounts"][0]["periods"][0]["opening_nav"] = "-100"
    assert (
        evaluate_portfolio_attribution(spec)["portfolio"][0]["risk_attribution"]["status"]
        == "unavailable"
    )
    spec = portfolio()
    spec["risk_models"][0]["covariance"] = [[-1e-14, 0, 0], [0, 0, 0], [0, 0, 0]]
    with pytest.raises(ValueError, match="PSD"):
        evaluate_portfolio_attribution(spec)
    spec = portfolio()
    spec["risk_models"][0]["covariance"] = [[0] * 3 for _ in range(3)]
    assert (
        evaluate_portfolio_attribution(spec)["portfolio"][0]["risk_attribution"][
            "volatility_contributions"
        ]
        is None
    )
    source, output = tmp_path / "input.json", tmp_path / "report"
    source.write_text(json.dumps(portfolio()), encoding="utf-8")
    main(["--input", str(source), "--out", str(output)])
    main(["--input", str(source), "--out", str(output), "--verify"])
    with pytest.raises(FileExistsError):
        run_report(source, output)
    (output / "components.csv").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="re-evaluation"):
        run_report(source, output, verify=True)
