from __future__ import annotations

import json
from decimal import Decimal

import pandas as pd
import pytest
from test_cash_price_bridge import SALE, T0, _inputs, _save

from quant_report_hub import execution_diagnostics as diagnostics
from quant_report_hub.cli import main
from quant_report_hub.execution_references import digest, fingerprint


def policy(tmp_path, **changes):
    value = {
        "schema_version": "quant-report-hub.execution-cost-policy/v1",
        "training_end": (T0 + pd.Timedelta(hours=1)).isoformat(),
        "holdout_start": (SALE - pd.Timedelta(hours=1)).isoformat(),
        "minimum_train_orders": 1,
        "minimum_holdout_orders": 1,
        "adverse_budget_bps": "50",
    }
    value.update(changes)
    return _save(tmp_path / "cost-policy.json", value)


def test_signed_cost_fit_uses_training_only_and_keeps_native_account(tmp_path):
    source, ref, ref_sha = _inputs(tmp_path)
    config, config_sha = policy(tmp_path)
    before = fingerprint([*source.rglob("*.*"), *ref.parent.iterdir(), config])
    out = tmp_path / "diagnostics"
    result = diagnostics.write_execution_diagnostics(
        source,
        references=ref,
        references_sha256=ref_sha,
        policy=config,
        policy_sha256=config_sha,
        out_dir=out,
    )
    summary = result["summary"]
    assert summary["status"] == "computed"
    assert summary["training_orders"] == summary["holdout_orders"] == 1
    assert Decimal(summary["fitted_adverse_bps"]) == Decimal(10000) / Decimal(99)
    assert Decimal(summary["holdout_adverse_bps"]) == -Decimal(20000) / Decimal(122)
    assert summary["holdout_budget_breaches"] == 0
    assert result["real_execution_calibrated"] is False
    assert result["references"]["source"]["evidence_kind"] == "synthetic"
    assert fingerprint(before) == before
    verified = diagnostics.verify_execution_diagnostics(
        source,
        references=ref,
        references_sha256=ref_sha,
        policy=config,
        policy_sha256=config_sha,
        report_dir=out,
        manifest_sha256=digest((out / "manifest.json").read_bytes()),
    )
    assert result == verified
    assert "不是纯市场冲击" in (out / "report.html").read_text(encoding="utf-8")


def test_insufficient_samples_are_explicit_and_do_not_fit(tmp_path):
    source, ref, ref_sha = _inputs(tmp_path)
    config, sha = policy(tmp_path, minimum_train_orders=2, minimum_holdout_orders=2)
    result = diagnostics.write_execution_diagnostics(
        source,
        references=ref,
        references_sha256=ref_sha,
        policy=config,
        policy_sha256=sha,
        out_dir=tmp_path / "out",
    )
    summary = result["summary"]
    assert summary["status"] == "insufficient_samples"
    assert summary["fitted_adverse_bps"] is None
    assert summary["holdout_prediction_error_bps"] is None
    assert {"insufficient_training_orders", "insufficient_holdout_orders"} == set(
        summary["reasons"]
    )


def test_partial_fills_count_once_and_crossing_cutoff_is_excluded():
    base = {
        "order_id": "one",
        "event_time": T0,
        "accepted_at": T0,
        "instrument_id": "A",
        "side": "buy",
        "currency": "CNY",
        "reference_price": "10",
        "quantity": "2",
        "raw_adverse_cost": "1",
    }
    fills = [dict(base, fill_id="f1"), dict(base, fill_id="f2", event_time=SALE)]
    config = {
        "training_end": T0 + pd.Timedelta(hours=1),
        "holdout_start": SALE - pd.Timedelta(hours=1),
        "minimum_train_orders": 1,
        "minimum_holdout_orders": 1,
        "adverse_budget_bps": Decimal(50),
    }
    orders, summary = diagnostics.summarize_orders(fills, config)
    assert len(orders) == 1 and orders[0]["fills"] == 2
    assert orders[0]["partition"] == "excluded_crosses_training_end"
    assert summary["excluded_orders"] == 1
    assert summary["training_orders"] == summary["holdout_orders"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"training_end": "2026-01-01"},
        {"holdout_start": T0.isoformat()},
        {"minimum_train_orders": True},
        {"minimum_holdout_orders": 0},
        {"adverse_budget_bps": "NaN"},
        {"adverse_budget_bps": "-1"},
        {"extra": "forbidden"},
    ],
)
def test_invalid_policy_never_publishes(tmp_path, changes):
    source, ref, ref_sha = _inputs(tmp_path)
    config, sha = policy(tmp_path, **changes)
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        diagnostics.write_execution_diagnostics(
            source,
            references=ref,
            references_sha256=ref_sha,
            policy=config,
            policy_sha256=sha,
            out_dir=out,
        )
    assert not out.exists()


def test_rehashed_tampered_report_is_rejected(tmp_path):
    source, ref, ref_sha = _inputs(tmp_path)
    config, sha = policy(tmp_path)
    out = tmp_path / "out"
    args = {"references": ref, "references_sha256": ref_sha, "policy": config, "policy_sha256": sha}
    diagnostics.write_execution_diagnostics(source, **args, out_dir=out)
    (out / "orders.csv").write_text("fake")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["orders.csv"] = digest(b"fake")
    manifest_path, manifest_sha = _save(out / "manifest.json", manifest)
    with pytest.raises(ValueError, match="重算"):
        diagnostics.verify_execution_diagnostics(
            source, **args, report_dir=out, manifest_sha256=manifest_sha
        )
    assert manifest_path.exists()


def test_cli_binds_policy_and_source_hashes(tmp_path, capsys):
    source, ref, ref_sha = _inputs(tmp_path)
    config, sha = policy(tmp_path)
    args = [
        "execution-cost-diagnostics",
        "--run-dir",
        str(source),
        "--references",
        str(ref),
        "--references-sha256",
        ref_sha,
        "--policy",
        str(config),
        "--policy-sha256",
        sha,
        "--out-dir",
        str(tmp_path / "out"),
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["real_execution_calibrated"] is False
    args[args.index(sha)] = "0" * 64
    args[-1] = str(tmp_path / "bad")
    assert main(args) == 1
    assert not (tmp_path / "bad").exists()


def test_empty_training_and_holdout_windows_remain_unavailable():
    config = {
        "training_end": T0,
        "holdout_start": SALE,
        "minimum_train_orders": 1,
        "minimum_holdout_orders": 2,
        "adverse_budget_bps": Decimal(50),
    }
    orders, summary = diagnostics.summarize_orders([], config)
    assert not orders and summary["status"] == "no_trades"
    assert summary["fitted_adverse_bps"] is None
    assert summary["holdout_adverse_bps"] is None
    base = {
        "event_time": T0,
        "accepted_at": T0,
        "instrument_id": "A",
        "side": "buy",
        "currency": "CNY",
        "reference_price": "10",
        "quantity": "2",
        "raw_adverse_cost": "1",
    }
    rows = [
        dict(base, order_id="train"),
        dict(base, order_id="train", quantity="8", raw_adverse_cost="-2"),
        dict(base, order_id="gap", accepted_at=T0 + pd.Timedelta(minutes=1)),
        dict(base, order_id="test", accepted_at=SALE, event_time=SALE),
    ]
    orders, summary = diagnostics.summarize_orders(rows, config)
    assert summary["status"] == "insufficient_samples"
    assert summary["training_orders"] == 1
    assert Decimal(summary["fitted_adverse_bps"]) == -100
    assert summary["holdout_prediction_error_bps"] is None
    assert summary["excluded_orders"] == 1
    assert summary["holdout_budget_breaches"] == 1
    test = next(row for row in orders if row["partition"] == "holdout")
    assert Decimal(test["predicted_signed_cost"]) == Decimal("-0.2")


def test_duplicate_policy_fields_rejected(tmp_path):
    config, _ = policy(tmp_path)
    raw = config.read_bytes().replace(
        b'"minimum_train_orders": 1', b'"minimum_train_orders": 1, "minimum_train_orders": 2'
    )
    config.write_bytes(raw)
    with pytest.raises(ValueError, match="duplicate|重复"):
        diagnostics._read_policy(config, digest(raw))


def test_output_cannot_replace_sources_or_existing_report(tmp_path):
    source, ref, ref_sha = _inputs(tmp_path)
    config, sha = policy(tmp_path)
    args = {"references": ref, "references_sha256": ref_sha, "policy": config, "policy_sha256": sha}
    before = fingerprint([*source.rglob("*.*"), *ref.parent.iterdir(), config])
    for target in (source / "report", ref.parent / "report", config):
        with pytest.raises((ValueError, FileExistsError)):
            diagnostics.write_execution_diagnostics(source, **args, out_dir=target)
    out = tmp_path / "out"
    diagnostics.write_execution_diagnostics(source, **args, out_dir=out)
    with pytest.raises((ValueError, FileExistsError)):
        diagnostics.write_execution_diagnostics(source, **args, out_dir=out)
    assert fingerprint(before) == before
