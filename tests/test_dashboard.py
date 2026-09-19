from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

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
        "targets": [{"symbol": "TEST", "quantity": 1}],
        "proposed_trades": [
            {"symbol": "TEST", "quantity": 1, "side": "buy", "order_id": "order-1"}
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
        lambda c: c["proposed_trades"][0].update(side="invalid"),
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
