import json

import pytest
from quant_lab.research import execute_study

from quant_report_hub.research_workbench import diagnose, load_study, render_study


def recipe():
    return {
        "schema_version": "quant.research-recipe/v1",
        "study_id": "test",
        "hypothesis": "<script>unsafe</script>",
        "mode": "exploratory",
        "backend": "equity",
        "inputs": {"bundle": "inputs"},
        "interval": {"start": "2024-01-01", "end": "2024-06-01"},
        "factors": {"momentum_20d": 1},
        "strategy": {
            "family": "rank",
            "frequency": "weekly",
            "top_n": 2,
            "max_weight": 0.25,
            "cash_buffer": 0.5,
            "trend_window": 60,
        },
        "costs": {
            "initial_capital": 100000,
            "commission": 0.0003,
            "min_commission": 5,
            "stamp_tax": 0.0005,
            "slippage": 0.001,
            "participation_rate": 0.01,
        },
        "diagnostics": {"cost_multipliers": [2], "signal_delays": [1]},
    }


def test_verified_report_escapes_source_and_explains_cost_difference(tmp_path):
    def executor(spec, candidate, out):
        if candidate["name"] == "delay_1":
            raise ValueError("missing prices")
        return {
            "scope": "retrospective",
            "risk_summary": {"model_kind": "statistical_proxy", "target_rejections": 2},
            "metrics": {
                "total_return": 0.01 * candidate["cost_multiplier"],
                "max_drawdown": -0.01,
                "sharpe": None,
                "fills": 1,
                "cost_total": 10,
            },
            "comparison": {"costs": candidate["cost_multiplier"]},
            "segments": [],
            "limitations": [],
        }

    execute_study(recipe(), tmp_path, identity={"code": "a"}, data_identity={}, executor=executor)
    report = render_study(tmp_path / "study.json", tmp_path / "report.html")
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in html
    assert "<script>unsafe</script>" not in html
    assert "风险执行证据" in html and "target_rejections" in html
    assert not report["comparison"]["comparable"]
    assert any(r["code"] == "INCOMPLETE_STUDY" for r in report["findings"])
    assert any(r["code"] == "NET_BASELINE_DIFFERENCE" for r in report["findings"])
    with pytest.raises(ValueError, match="overwrite"):
        render_study(tmp_path / "study.json", tmp_path / "experiments.db")
    summary = json.loads((tmp_path / "study.json").read_text())
    summary["results"][0]["metrics"]["total_return"] = 10
    (tmp_path / "study.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="differs"):
        load_study(tmp_path / "study.json")
    summary["results"].pop()
    (tmp_path / "study.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="omits"):
        load_study(tmp_path / "study.json")


def test_no_baseline_and_fixture_do_not_claim_alpha():
    assert diagnose({"results": []})[0]["code"] == "BASELINE_UNAVAILABLE"
    result = {"candidate": {"name": "base"}, "status": "completed", "scope": "fixture-only"}
    assert diagnose({"results": [result]})[0]["code"] == "FIXTURE_ONLY"


@pytest.mark.parametrize("tamper", ["omit_failed", "reorder", "change_time"])
def test_report_verifies_entire_attempt_history_after_retry(tmp_path, tamper):
    fail_base = True

    def executor(spec, candidate, out):
        if fail_base and candidate["name"] == "base":
            raise ValueError("first attempt failed")
        return {"scope": "retrospective", "metrics": {"total_return": 0}, "comparison": {}}

    execute_study(recipe(), tmp_path, identity={"code": "a"}, data_identity={}, executor=executor)
    fail_base = False
    execute_study(recipe(), tmp_path, identity={"code": "a"}, data_identity={}, executor=executor)
    path = tmp_path / "study.json"
    summary = load_study(path)
    assert summary["failed"] == 0
    assert any(event["status"] == "failed" for event in summary["attempts"])
    if tamper == "omit_failed":
        summary["attempts"] = [e for e in summary["attempts"] if e["status"] != "failed"]
    elif tamper == "reorder":
        summary["attempts"].reverse()
    else:
        summary["attempts"][0]["recorded_at"] = "2000-01-01T00:00:00+00:00"
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="Attempt history"):
        load_study(path)
