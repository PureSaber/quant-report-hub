import json

import pytest
from measurement_helpers import measurement, write_measured
from quant_lab.scanner import scan_run
from quant_lab.store import ExperimentStore

from quant_report_hub.cli import main
from quant_report_hub.dashboard import experiment_panels
from quant_report_hub.dashboard_data import read_experiments


def test_actual_compare_cli_compounds_includes_opening_and_blocks_different_basis(tmp_path, capsys):
    for name in ["a", "b"]:
        write_measured(tmp_path / name)
    args = [
        "compare",
        "--output-root",
        str(tmp_path),
        "--run-ids",
        "a",
        "b",
        "--out-dir",
        str(tmp_path / "report"),
    ]
    assert main(args) == 0
    report = json.loads((tmp_path / "report" / "measurement-comparison.json").read_text())
    assert report["comparison"]["comparable"]
    assert report["metrics"][0]["total_return"] == pytest.approx(-0.01)
    assert report["metrics"][0]["max_drawdown"] == pytest.approx(-0.1)
    assert report["metrics"][0]["annualized_metrics"] is None
    value = measurement()
    value["basis"]["currency"] = "USD"
    write_measured(tmp_path / "c", value)
    assert (
        main(
            [
                "compare",
                "--output-root",
                str(tmp_path),
                "--run-ids",
                "a",
                "c",
                "--out-dir",
                str(tmp_path / "bad"),
            ]
        )
        == 2
    )
    assert "currency" in capsys.readouterr().err
    assert not (tmp_path / "bad" / "14_multi_nav.png").exists()


def test_dashboard_key_comes_from_common_validator_legacy_metrics_remain_visible(tmp_path):
    db = tmp_path / "lab.db"
    store = ExperimentStore(db)
    for name in ["a", "b"]:
        write_measured(tmp_path / name)
        run = scan_run(tmp_path / name)
        store.upsert(
            project=run.project,
            run_id=run.run_id,
            run_path=run.run_path,
            run_type=run.run_type,
            metrics=run.metrics,
        )
    rows, error = read_experiments(db)
    assert not error and all(row["measurement"] for row in rows)
    table, _cards = experiment_panels(rows, tmp_path / "dash.html")
    assert 'data-basis="sha256:' in table
    assert "只读来源指标" in table
    legacy = tmp_path / "old"
    legacy.mkdir()
    store.upsert(
        project="legacy",
        run_id="old",
        run_path=str(legacy),
        run_type="equity",
        metrics={"total_return": 0.123},
    )
    rows, _ = read_experiments(db)
    old = next(r for r in rows if r["project"] == "legacy")
    table, _ = experiment_panels([old], tmp_path / "dash.html")
    assert "disabled" in table and "0.123" in table
    assert old["measurement"] is None


def test_legacy_compare_is_explicitly_unavailable(tmp_path, capsys):
    for name in ["a", "b"]:
        path = tmp_path / name
        path.mkdir()
        (path / "capital_curves.csv").write_text("date,s\n2025-01-01,10000\n2025-01-02,10100\n")
    assert (
        main(
            [
                "compare",
                "--adapter",
                "equity",
                "--output-root",
                str(tmp_path),
                "--run-ids",
                "a",
                "b",
                "--out-dir",
                str(tmp_path / "out"),
            ]
        )
        == 2
    )
    assert "legacy or missing" in capsys.readouterr().err
