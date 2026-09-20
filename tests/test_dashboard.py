from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from quant_lab.store import ExperimentStore
from test_v2_attribution import _write_run

from quant_report_hub.cli import main
from quant_report_hub.dashboard import write_dashboard
from quant_report_hub.dashboard_data import (
    dashboard_snapshot,
    load_decision_root,
    read_experiments,
    read_json,
    timestamp,
)
from quant_report_hub.dashboard_exports import render_pdf, write_daily_package
from quant_report_hub.dashboard_insights import risk_summary
from quant_report_hub.dashboard_operational import execution_summary
from quant_report_hub.dashboard_server import default_serve_root, source_fingerprint

NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "decisions"
    run = root / "run-1"
    _write_run(run, source=[], costs=[], nav_delta=0)
    manifest = run / "standard/v2/run_manifest.json"
    card = {
        "schema_version": "quant.decision/v1",
        "run_id": run.name,
        "status": "paper_ready",
        "scope": "paper_simulation_only",
        "as_of": "2026-09-18",
        "generated_at": "2026-09-19T07:00:00Z",
        "valid_until": "2030-09-21T09:30:00+08:00",
        "data_quality": {"passed": True, "symbols": 4},
        "validation": {
            "passed": True,
            "forward_observation_days": 0,
            "net_performance": {"total_return": 0.0, "sharpe": None},
        },
        "current_positions": [],
        "targets": [{"symbol": "instrument-1", "quantity": 1}],
        "proposed_trades": [
            {"symbol": "instrument-1", "quantity": 1, "side": "buy", "order_id": "order-1"}
        ],
        "estimated_cost": {"fees": 1.0, "slippage": 2.0, "total": 3.0, "currency": "USD"},
        "risk": {"nav": 1000},
        "reasons": ["fixture only"],
        "evidence": {
            "standard_manifest": str(manifest),
            "standard_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "code_version": "a" * 40,
        },
    }
    dump(run / "decision.json", card)
    dump(
        root / "latest.json",
        {"run_id": run.name, "status": "paper_ready", "decision": "run-1/decision.json"},
    )
    return root, run, card


def test_fresh_decision_source_integrity_and_readonly_publication(source, tmp_path):
    root, _, _ = source
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    current = load_decision_root(root, NOW)["current"]
    assert current["status"] == "paper_ready", current["error"]
    out = write_dashboard([root], tmp_path / "reports/index.html", now=NOW)
    page = out.read_text(encoding="utf-8")
    assert 'data-eligible="true"' in page
    assert "<section data-paper-actions hidden>" in page  # fail closed when JavaScript is disabled
    assert "3.00 USD" in page
    assert "../decisions/run-1/standard/v2/config.json" in page
    assert "决策收件箱" in page
    assert "计划与实际执行" in page
    assert "前向效果跟踪" in page
    assert "全部成交" in page
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert not list(out.parent.glob("*.tmp"))


@pytest.mark.parametrize("status", ["blocked", "observe"])
def test_nonactionable_producer_states(source, tmp_path, status):
    root, run, card = source
    card.update(status=status, targets=[], proposed_trades=[])
    if status == "blocked":
        card.update(as_of="", valid_until=None, evidence={}, data_quality={}, validation={})
    dump(run / "decision.json", card)
    dump(
        root / "latest.json",
        {"run_id": run.name, "status": status, "decision": str(run / "decision.json")},
    )
    item = load_decision_root(root, NOW)["current"]
    assert item["status"] == status
    page = write_dashboard([root], tmp_path / "view.html", now=NOW).read_text(encoding="utf-8")
    assert "<section data-paper-actions" not in page


def test_expired_decision_never_renders_proposals(source, tmp_path):
    root, run, card = source
    card["valid_until"] = "2026-09-19T10:00:00Z"
    dump(run / "decision.json", card)
    assert load_decision_root(root, NOW)["current"]["status"] == "expired"
    page = write_dashboard([root], tmp_path / "view.html", now=NOW).read_text(encoding="utf-8")
    assert "<section data-paper-actions" not in page
    assert "已过期 · 仅供复盘" in page
    assert "order-1" not in page


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(schema_version="quant.decision/v999"),
        lambda c: c.pop("as_of"),
        lambda c: c.update(run_id="another-run"),
        lambda c: c.update(status="live_ready"),
        lambda c: c.update(scope="live"),
        lambda c: c.update(risk=[]),
        lambda c: c.update(current_positions=[1]),
        lambda c: c.update(reasons="broken"),
        lambda c: c.update(generated_at="2099-01-01T00:00:00Z"),
        lambda c: c.update(generated_at="2026-09-19T07:00:00"),
        lambda c: c.update(generated_at=None),
        lambda c: c.update(as_of="2099-01-01"),
        lambda c: c.update(valid_until="2025-01-01T00:00:00Z"),
        lambda c: c.update(status="blocked"),
        lambda c: c["data_quality"].update(passed="true"),
        lambda c: c["targets"][0].update(symbol=""),
        lambda c: c["targets"][0].update(quantity=-1),
        lambda c: c["targets"][0].update(weight="invalid"),
        lambda c: c["targets"].append(dict(c["targets"][0])),
        lambda c: c["proposed_trades"][0].update(side="invalid"),
        lambda c: c["proposed_trades"].append(dict(c["proposed_trades"][0])),
        lambda c: c["estimated_cost"].update(total=None),
        lambda c: c["evidence"].update(standard_manifest="../outside/run_manifest.json"),
        lambda c: c["evidence"].update(standard_manifest_sha256="0" * 64),
        lambda c: c["evidence"].update(code_version="wrong"),
    ],
)
def test_malformed_cards_fail_closed(source, mutate):
    root, run, card = source
    mutate(card)
    dump(run / "decision.json", card)
    item = load_decision_root(root, NOW)["current"]
    assert item["status"] == "invalid"
    assert item["error"]
    assert not item["card"]


def test_tampered_ledger_has_no_fallback(source):
    root, run, _ = source
    (run / "standard/v2/metrics.json").write_text('{"total_return":999}', encoding="utf-8")
    item = load_decision_root(root, NOW)["current"]
    assert item["status"] == "invalid"
    assert not item["card"]


@pytest.mark.parametrize(
    "pointer",
    [
        None,
        [],
        {"run_id": "../escape"},
        {"run_id": ".."},
        {"run_id": "run-1", "status": "paper_ready", "decision": "elsewhere/decision.json"},
        {"run_id": "run-1", "status": "blocked", "decision": "run-1/decision.json"},
        {"run_id": "missing", "status": "blocked", "decision": "missing/decision.json"},
    ],
)
def test_broken_latest_never_promotes_previous_success(source, tmp_path, pointer):
    root, _, _ = source
    if pointer is None:
        (root / "latest.json").unlink()
    else:
        dump(root / "latest.json", pointer)
    item = load_decision_root(root, NOW)["current"]
    assert item["status"] == "invalid"
    page = write_dashboard([root], tmp_path / "view.html", now=NOW).read_text(encoding="utf-8")
    assert "<section data-paper-actions" not in page


def test_escaping_and_multiple_roots(source, tmp_path):
    root, run, card = source
    attack = '</script><script>alert("x")</script>'
    card["reasons"] = [attack]
    card["risk"] = {"name": attack}
    dump(run / "decision.json", card)
    page = write_dashboard([root, tmp_path / "missing"], tmp_path / "view.html", now=NOW).read_text(
        encoding="utf-8"
    )
    assert attack not in page
    assert "&lt;/script&gt;" in page
    assert 'data-status="paper_ready"' in page and 'data-status="invalid"' in page


@pytest.mark.parametrize("contents", ["[]", '{"x":NaN}', '{"x":1e500}', "{"])
def test_invalid_json_is_rejected(tmp_path, contents):
    path = tmp_path / "data.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        read_json(path)


def test_size_limit_and_naive_clock(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    path.write_text('{"value":123}', encoding="utf-8")
    monkeypatch.setattr("quant_report_hub.dashboard_data.MAX_JSON_BYTES", 4)
    with pytest.raises(ValueError, match="exceeds"):
        read_json(path)
    with pytest.raises(ValueError, match="timezone"):
        dashboard_snapshot([], None, NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone"):
        timestamp("2026-01-01T00:00:00")


def make_index(
    path, run, *, project="m5-golden", run_type="standard_v2_backtest-ledger", metrics=None
):
    store = ExperimentStore(path)
    store.upsert(
        project=project,
        run_id=run.name,
        run_path=str(run.resolve()),
        run_type=run_type,
        metrics=metrics or {"total_return": 999},
    )


def test_index_uses_verified_source_not_stale_cached_metrics(source, tmp_path):
    root, run, _ = source
    db = tmp_path / "experiments.db"
    make_index(db, run)
    before = db.read_bytes()
    rows, error = read_experiments(db)
    assert not error and rows[0]["verified"]
    assert rows[0]["metrics"] == {"fixture": True}
    assert before == db.read_bytes()
    write_dashboard([root], tmp_path / "view.html", db=db, now=NOW)
    assert before == db.read_bytes()
    (run / "standard/v2/metrics.json").unlink()
    rows, _ = read_experiments(db)
    assert rows[0]["error"] and not rows[0]["metrics"]


def test_index_identity_mismatch_and_missing_source(source, tmp_path):
    _, run, _ = source
    db = tmp_path / "experiments.db"
    make_index(db, run, project="wrong")
    make_index(db, tmp_path / "deleted")
    rows, _ = read_experiments(db)
    assert all(row["error"] and not row["verified"] for row in rows)


def test_legacy_index_is_labelled_and_comparison_retains_portfolios(tmp_path):
    db = tmp_path / "experiments.db"
    run = tmp_path / "legacy"
    run.mkdir()
    make_index(
        db,
        run,
        run_type="equity_backtest",
        metrics={
            "backtest_stats": [
                {"portfolio": "Q1", "total_return": 0.1},
                {"portfolio": "Q2", "sharpe": None},
            ],
        },
    )
    rows, _ = read_experiments(db)
    assert not rows[0]["verified"] and not rows[0]["error"]
    page = write_dashboard(
        [tmp_path / "missing"], tmp_path / "view.html", db=db, now=NOW
    ).read_text(encoding="utf-8")
    assert "索引缓存 · 未校验" in page and "10.00%" in page
    assert "Q1" in page and "Q2" in page
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE experiments SET metrics_json='[]'")
    assert read_experiments(db)[0][0]["error"]


def test_unavailable_index_does_not_create_or_change_database(tmp_path):
    missing = tmp_path / "absent.db"
    assert read_experiments(missing)[1]
    assert not missing.exists()
    corrupt = tmp_path / "bad.db"
    corrupt.write_text("not sqlite", encoding="utf-8")
    assert read_experiments(corrupt)[1]
    assert corrupt.read_text(encoding="utf-8") == "not sqlite"


def test_output_must_not_overwrite_sources(source, tmp_path):
    root, run, _ = source
    with pytest.raises(ValueError, match="outside decision roots"):
        write_dashboard([root], run / "standard/view.html", now=NOW)
    assert (
        main(["dashboard", "--decision-root", str(root), "--out", str(root / "latest.json")]) == 1
    )
    db = tmp_path / "experiments.html"
    make_index(db, run)
    with pytest.raises(ValueError, match="database"):
        write_dashboard([], db, db=db, now=NOW)
    with pytest.raises(ValueError, match="indexed run"):
        write_dashboard([], run / "view.html", db=db, now=NOW)


def test_dashboard_cli_publishes_missing_source_state(tmp_path, capsys):
    out = tmp_path / "index.html"
    assert main(["dashboard", "--decision-root", str(tmp_path / "missing"), "--out", str(out)]) == 0
    assert "来源不可用" in out.read_text(encoding="utf-8")
    assert "generated research dashboard" in capsys.readouterr().out
    assert out.with_suffix(".alerts.json").is_file()
    assert out.with_suffix(".html.status.json").is_file()


def test_execution_and_immature_outcome_are_source_backed(source):
    root, _, _ = source
    current = dashboard_snapshot([root], None, NOW)["sources"][0]["current"]
    execution = current["execution"]
    assert execution["available"]
    assert execution["matched_orders"] == 1
    assert execution["orders_with_fills"] == 1
    assert execution["fill_records"] == 1
    assert execution["orders"][0]["fill_rate"] == 1.0
    assert execution["orders"][0]["average_fill_price"] == 101.0
    assert execution["orders"][0]["actual_cost"] == 0.0
    assert execution["orders"][0]["evidence_check"] == "一致"
    assert execution["positions"][0]["symbol"] == "instrument-1"
    assert current["outcome"]["observed_days"] == 0
    assert not current["outcome"]["available"]
    assert all(row["return"] is None for row in current["outcome"]["windows"])


def test_forward_windows_require_declared_maturity(source):
    root, run, card = source
    card["validation"]["forward_observation_days"] = 2
    dump(run / "decision.json", card)
    outcome = load_decision_root(root, NOW)["current"]["outcome"]
    assert outcome["available"]
    assert outcome["observed_return"] == 0.0
    assert outcome["windows"] == [
        {"days": 1, "return": 0.0},
        {"days": 5, "return": None},
        {"days": 20, "return": None},
    ]


def test_missing_or_mismatched_order_evidence_is_explicit(source):
    root, run, card = source
    card["proposed_trades"][0]["order_id"] = "missing-order"
    dump(run / "decision.json", card)
    execution = load_decision_root(root, NOW)["current"]["execution"]
    assert not execution["available"]
    assert execution["matched_orders"] == 0
    assert "没有匹配记录" in execution["notice"]
    assert execution["orders"][0]["order_status"] == "source_missing"


def test_current_target_change_uses_most_recent_valid_history(source):
    root, run, card = source
    previous = root / "run-0"
    _write_run(previous, source=[], costs=[], nav_delta=0)
    previous_manifest = previous / "standard/v2/run_manifest.json"
    old_card = json.loads(json.dumps(card))
    old_card.update(
        run_id="run-0",
        generated_at="2026-09-18T07:00:00Z",
        targets=[{"symbol": "old-symbol", "quantity": 2, "weight": 0.2}],
        proposed_trades=[
            {"symbol": "old-symbol", "quantity": 2, "side": "buy", "order_id": "old-order"}
        ],
    )
    old_card["evidence"].update(
        standard_manifest=str(previous_manifest),
        standard_manifest_sha256=hashlib.sha256(previous_manifest.read_bytes()).hexdigest(),
    )
    dump(previous / "decision.json", old_card)
    current = load_decision_root(root, NOW)["current"]
    assert current["change"]["available"]
    assert current["change"]["previous_run_id"] == "run-0"
    assert current["change"]["counts"]["new"] == 1
    assert current["change"]["counts"]["exit"] == 1
    assert "新增 1" in current["change"]["summary"]
    assert run.name == current["run_id"]


def test_nonactionable_current_state_does_not_imply_liquidation(source):
    root, run, card = source
    card.update(status="observe", targets=[], proposed_trades=[])
    dump(run / "decision.json", card)
    dump(
        root / "latest.json",
        {"run_id": run.name, "status": "observe", "decision": "run-1/decision.json"},
    )
    change = load_decision_root(root, NOW)["current"]["change"]
    assert not change["available"]
    assert change["rows"] == []
    assert "没有可比较" in change["summary"]


def test_snapshot_builds_risk_alert_and_account_views(source):
    root, _, _ = source
    snapshot = dashboard_snapshot([root], None, NOW)
    assert snapshot["accounts"] == [
        {
            "source": "decisions",
            "project": "m5-golden",
            "strategies": "alpha",
            "account_id": "acct-1",
            "status": "paper_ready",
            "nav": 1000.0,
            "cash": 900.0,
            "market_value": 100.0,
            "currency": "USD",
            "planned_orders": 1,
            "filled_orders": 1,
            "alerts": 0,
            "as_of": "2026-09-18",
        }
    ]
    assert [row["code"] for row in snapshot["alerts"]] == ["forward_window_immature"]
    assert snapshot["sources"][0]["current"]["risk_summary"]["available"]


def test_risk_summary_flags_concentration_drawdown_and_cash():
    summary = risk_summary(
        {
            "targets": [{"symbol": "AAA", "weight": 0.8}, {"symbol": "BBB", "weight": 0.3}],
            "risk": {
                "nav": 1000,
                "currency": "CNY",
                "max_single_weight": 0.4,
                "max_drawdown": 0.1,
                "allocation": {"max_position_weight": 0.5, "cash_buffer": 0.05},
            },
            "validation": {"net_performance": {"max_drawdown": -0.2}},
            "estimated_cost": {"total": 2},
        }
    )
    assert {row["code"] for row in summary["breaches"]} == {
        "target_concentration",
        "drawdown_limit",
        "target_leverage",
    }
    assert summary["metrics"][-1]["value"] == 20.0


def test_risk_summary_surfaces_pre_order_portfolio_check():
    summary = risk_summary(
        {
            "targets": [],
            "risk": {
                "nav": 100000,
                "portfolio_checks": [
                    {
                        "has_critical": True,
                        "metrics": {
                            "gross_weight": 0.8,
                            "cash_weight": 0.2,
                            "turnover": 0.8,
                            "positions": 2,
                            "industry_weights": {"bank": 0.55, "appliance": 0.25},
                        },
                        "alerts": [
                            {
                                "rule_id": "portfolio.max_industry_weight",
                                "severity": "critical",
                                "message": "bank exceeds the industry concentration limit",
                            }
                        ],
                    }
                ],
            },
        }
    )
    metrics = {item["label"]: item["value"] for item in summary["metrics"]}
    assert metrics["预计换手"] == 0.8
    assert metrics["最大行业权重"] == 0.55
    assert summary["breaches"][0]["code"] == "portfolio.max_industry_weight"


def test_execution_can_close_a_prior_order_from_cumulative_followup_runs(tmp_path, monkeypatch):
    event0 = datetime(2026, 9, 18, tzinfo=timezone.utc)
    event1 = datetime(2026, 9, 19, tzinfo=timezone.utc)

    def fake_rows(run, _manifest, name, _columns, *, filters=None):
        assert filters or name == "positions"
        if name == "orders":
            status = "accepted" if run.name == "first" else "filled"
            return [
                {
                    "event_time": event0 if status == "accepted" else event1,
                    "order_id": "future-order",
                    "account_id": "paper",
                    "instrument_id": "AAA",
                    "side": "buy",
                    "quantity_units": 10,
                    "quantity_scale": 0,
                    "status": status,
                    "filled_quantity_units": 0 if status == "accepted" else 10,
                    "filled_quantity_scale": 0,
                    "version": 1 if status == "accepted" else 2,
                }
            ]
        if name == "fills" and run.name != "first":
            return [
                {
                    "event_time": event1,
                    "fill_id": "fill-once",
                    "order_id": "future-order",
                    "account_id": "paper",
                    "instrument_id": "AAA",
                    "side": "buy",
                    "quantity_units": 10,
                    "quantity_scale": 0,
                    "price_units": 101,
                    "price_scale": 0,
                    "currency": "CNY",
                }
            ]
        if name == "costs" and run.name != "first":
            return [
                {
                    "cost_id": "cost-once",
                    "fill_id": "fill-once",
                    "cost_type": "commission",
                    "amount_units": 5,
                    "amount_scale": 0,
                    "currency": "CNY",
                }
            ]
        return []

    monkeypatch.setattr("quant_report_hub.dashboard_operational._rows", fake_rows)
    monkeypatch.setattr("quant_report_hub.dashboard_operational._artifact", lambda *_: None)
    first = SimpleNamespace(run_id="first")
    next_one = SimpleNamespace(run_id="next-one")
    next_two = SimpleNamespace(run_id="next-two")
    result = execution_summary(
        tmp_path / "first",
        first,
        {
            "proposed_trades": [
                {
                    "order_id": "future-order",
                    "symbol": "AAA",
                    "side": "buy",
                    "quantity": 10,
                    "estimated_execution_price": 100,
                }
            ]
        },
        followup_runs=[(tmp_path / "next-one", next_one), (tmp_path / "next-two", next_two)],
    )
    assert result["fill_records"] == 1
    assert result["orders_with_fills"] == 1
    assert result["orders"][0]["average_fill_price"] == 101.0
    assert result["actual_costs"] == [{"currency": "CNY", "amount": 5.0}]
    assert result["evidence_runs"] == ["first", "next-one", "next-two"]


def test_daily_package_exports_html_csv_json_and_manifest(source, tmp_path):
    root, _, _ = source
    snapshot = dashboard_snapshot([root], None, NOW)
    outputs = write_daily_package(snapshot, tmp_path / "daily", include_pdf=False)
    names = {path.name for path in outputs}
    assert {
        "index.html",
        "index.alerts.json",
        "index.html.status.json",
        "decisions.csv",
        "execution.csv",
        "outcomes.csv",
        "accounts.csv",
        "alerts.csv",
        "manifest.json",
    } == names
    manifest = json.loads((tmp_path / "daily/manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "quant-report-hub.daily-package/v1"
    assert len(manifest["files"]) == 8
    assert (tmp_path / "daily/decisions.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_pdf_export_uses_explicit_browser_and_validates_output(tmp_path, monkeypatch):
    browser = tmp_path / "browser.exe"
    browser.write_bytes(b"fixture")
    html = tmp_path / "index.html"
    html.write_text("<h1>daily</h1>", encoding="utf-8")

    def fake_run(command, **_kwargs):
        output = next(
            value.split("=", 1)[1] for value in command if value.startswith("--print-to-pdf=")
        )
        Path(output).write_bytes(b"%PDF-1.4\nfixture")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("quant_report_hub.dashboard_exports.subprocess.run", fake_run)
    pdf = render_pdf(html, tmp_path / "daily.pdf", browser=browser)
    assert pdf.read_bytes().startswith(b"%PDF")


def test_watch_fingerprint_and_default_root_change_with_inputs(source, tmp_path):
    root, _, _ = source
    out = tmp_path / "reports/dashboard.html"
    first = source_fingerprint([root], None)
    (root / "latest.json").touch()
    second = source_fingerprint([root], None)
    assert first != second
    assert default_serve_root([root], out).is_dir() or default_serve_root([root], out) == tmp_path
