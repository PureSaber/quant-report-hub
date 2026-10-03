import json

import pytest
from quant_lab.research import execute_study, file_hash
from quant_lab.trials import TrialRegistry
from test_research_workbench import recipe

from quant_report_hub.research_evidence import main, render_evidence
from quant_report_hub.research_workbench import diagnose, load_study, render_study


@pytest.mark.parametrize("schema", ["quant.family-evidence/v1", "quant.paired-evidence/v1"])
def test_evidence_cards_keep_unavailable_and_escape_snapshot(tmp_path, schema, monkeypatch):
    value = {
        "schema": schema,
        "audit": {"available": False, "failure": "<script>alert(1)</script>"},
        "methods": {"dsr": {"available": False, "reason": "failed candidate"}},
        "available": False,
        "attempts": [{"status": "failed"}],
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "report.html"
    render_evidence(path, output, expected_sha256=file_hash(path))
    text = output.read_text(encoding="utf-8")
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "failed" in text and "投资" in text
    with pytest.raises(ValueError, match="hash"):
        render_evidence(path, output, expected_sha256="wrong")
    with pytest.raises(ValueError, match="separate"):
        render_evidence(path, path, expected_sha256=file_hash(path))
    monkeypatch.setattr(
        "sys.argv", ["report", str(path), "--output", str(output), "--sha256", file_hash(path)]
    )
    main()


def test_external_registry_and_continuous_mode_are_explicit(tmp_path):
    spec = recipe()
    spec["validation"] = {"train_sessions": 20, "test_sessions": 5, "account_policy": "continuous"}
    registry = TrialRegistry(tmp_path / "shared.db")
    root = tmp_path / "study"

    def executor(*args):
        return {
            "scope": "historical",
            "metrics": {"total_return": 0},
            "objective_evaluation": {"status": "insufficient_evidence"},
        }

    result = execute_study(
        spec,
        root,
        identity={"code": "frozen"},
        data_identity={"code": "fixture"},
        executor=executor,
        registry=registry,
    )
    assert load_study(root / "study.json", registry_path=registry.path) == result
    output = root / "report.html"
    render_study(root / "study.json", output, registry_path=registry.path)
    html = output.read_text(encoding="utf-8")
    assert "连续账户" in html and "每折重新入场" not in html
    assert any(row["code"] == "EX_ANTE_OBJECTIVE" for row in diagnose(result))


def test_real_family_collector_failures_and_missing_members_are_visible(tmp_path):
    import pandas as pd
    from quant_lab.family_evidence import collect_family, evaluate_family

    registry = TrialRegistry(tmp_path / "shared.db")
    basis = {
        "currency": "USD",
        "benchmark_id": "cash",
        "cost_policy": "net-v1",
        "periods_per_year": 252,
        "sample_kind": "synthetic",
    }
    registry.register_family(
        "family", {"study_ids": ["test", "missing-study"], "hypothesis": "h", "basis": basis}
    )
    spec = recipe()
    spec.update(family_id="family", measurement_basis=basis, diagnostics={})

    def executor(spec, candidate, out):
        if candidate["name"] == "base":
            raise ValueError("<script>missing price</script>")
        pd.Series([0.01, -0.01] * 32, index=pd.date_range("2024-01-01", periods=64)).to_csv(
            out / "returns.csv", header=["net_return"]
        )
        return {
            "comparison": {
                "start": "2024-01-01",
                "end": "2024-03-04",
                "currency": "USD",
                "costs": "net-v1",
            }
        }

    execute_study(
        spec,
        tmp_path / "study",
        identity={"code": "fixture"},
        data_identity={"code": "fixture"},
        executor=executor,
        registry=registry,
    )
    values, audit = collect_family(registry, "family")
    evidence = evaluate_family(values, audit)
    assert not audit["available"] and not evidence["methods"]
    source = tmp_path / "family.json"
    source.write_text(json.dumps(evidence), encoding="utf-8")
    output = tmp_path / "family.html"
    render_evidence(source, output, expected_sha256=file_hash(source))
    html = output.read_text(encoding="utf-8").split("<details>")[0]
    assert "家族统计结论不可用" in html and "missing-study:not_registered" in html
    assert "test / base" in html and "test / buy_hold" in html
    assert "&lt;script&gt;missing price&lt;/script&gt;" in html and "<script>" not in html
    assert source.read_text(encoding="utf-8") == json.dumps(evidence)


def test_unavailable_family_rejects_contradictory_statistical_pass(tmp_path):
    value = {
        "schema": "quant.family-evidence/v1",
        "audit": {"available": False},
        "methods": {"dsr": {"available": True, "evidence": {}}},
    }
    source = tmp_path / "family.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "family.html"
    with pytest.raises(ValueError, match="unavailable family"):
        render_evidence(source, output, expected_sha256=file_hash(source))
    assert not output.exists()
