import json
from copy import deepcopy

import pandas as pd
import pytest
from quant_lab.contracts_v2 import write_standard_run_v2
from quant_lab.counterfactuals import attribution, intervention_plan
from quant_lab.research import canonical, digest, file_hash
from test_cash_attribution import _frames
from test_research_workbench import recipe

from quant_report_hub.cli import main
from quant_report_hub.dashboard import write_dashboard_bundle
from quant_report_hub.dashboard_exports import write_daily_package, write_runtime_sidecars
from quant_report_hub.dashboard_server import published_files, source_fingerprint
from quant_report_hub.paired_data import _view, load_paired, paired_snapshot


def dump(path, value):
    path.write_text(canonical(value), encoding="utf-8")


def make_paired(root, *, offset=0, failure=None, hypothesis="fixture", risk_model=False):
    root.mkdir()
    spec = recipe()
    first = pd.Timestamp("2025-01-02") + pd.Timedelta(days=offset)
    spec.update(study_id=root.name, hypothesis=hypothesis, risk={"max_drawdown": 0.2})
    spec["interval"] = {
        "start": str(first.date()),
        "end": str((first + pd.Timedelta(days=3)).date()),
    }
    if risk_model:
        spec["risk_model"] = {"model_kind": "statistical_proxy"}
    base = {
        "name": "base",
        "factors": spec["factors"],
        "strategy": spec["strategy"],
        "cost_multiplier": 1,
        "signal_delay": 0,
        "risk": spec["risk"],
    }
    constrained = {**base, "strategy": {**base["strategy"], "family": "buy_hold"}}
    passive = {**constrained, "risk": {}, "risk_model": None}
    plan = intervention_plan(
        base,
        {"signal": {"volatility_20d": -1}, "fees": 0},
        benchmarks={
            "passive": passive,
            "same_risk_constrained": constrained,
            "cash": {"mode": "cash", "daily_return": 0},
        },
    )
    dump(
        root / "preregistration.json",
        {"recipe": spec, "plan": plan, "input_manifest_sha256": "a" * 64},
    )
    series, attempts = {}, []
    for name, request in {"base": base, **plan["variants"], **plan["benchmarks"]}.items():
        if name == "cash":
            continue
        if name == failure:
            attempts.append({"name": name, "status": "failed", "error": "<missing price>"})
            continue
        run = root / name
        run.mkdir()
        candidate = {k: deepcopy(v) for k, v in request.items() if k not in {"risk", "risk_model"}}
        candidate["name"] = name
        candidate["candidate_id"] = digest(candidate)[:20]
        resolved = deepcopy(spec)
        resolved["risk"] = request["risk"]
        if name == "passive":
            resolved.pop("risk_model", None)
        dump(run / "execution-definition.json", {"recipe": resolved, "candidate": candidate})
        frames = {
            name: frame.sort_values("event_time", kind="stable")
            for name, frame in _frames().items()
        }
        for frame in frames.values():
            frame["event_time"] = pd.to_datetime(frame["event_time"], utc=True) + pd.Timedelta(
                days=offset
            )
        write_standard_run_v2(
            run,
            project="a-share-multifactor",
            run_id=name,
            strategy_ids=["strategy"],
            profile="backtest-ledger",
            frames=frames,
            metrics={},
            config={"costs": {"max_holdings": 4, "max_position_weight": 0.2, "cash_buffer": 0.2}},
            code_version="a" * 40,
            internal_dependencies={"quant-lab": "v0.3.0"},
            random_seed=0,
            dataset_snapshots={"fixture": "sha256:cash-v1"},
            instrument_master_version="test",
            execution_model_version="test",
            base_currency="CNY",
            lineage={
                **{key: ["dataset:fixture"] for key in frames},
                "config": [],
                "metrics": ["dataset:fixture"],
            },
            created_at="2025-03-08T00:00:00+00:00",
        )
        returns = frames["returns"]
        dates = (
            pd.DatetimeIndex(returns.event_time)
            .tz_convert("Asia/Shanghai")
            .tz_localize(None)
            .normalize()
        )
        values = pd.Series(returns.net_return.to_numpy(), index=dates)
        values.to_csv(run / "returns.csv", header=["net_return"])
        series[name] = values
        result = {
            "scope": "synthetic-fixture",
            "comparison": {**spec["interval"], "currency": "CNY"},
            "artifacts": {
                p.relative_to(run).as_posix(): file_hash(p) for p in run.rglob("*") if p.is_file()
            },
        }
        dump(run / "result.json", result)
        attempts.append(
            {
                "name": name,
                "status": "completed",
                "result_sha256": file_hash(run / "result.json"),
                "definition_sha256": file_hash(run / "execution-definition.json"),
            }
        )
    dump(root / "attempts.json", attempts)
    value = {
        "schema": "quant.paired-evidence/v1",
        "plan_sha256": plan["sha256"],
        "preregistration_sha256": file_hash(root / "preregistration.json"),
        "attempts": attempts,
        "available": failure is None,
    }
    if failure is None:
        data = pd.DataFrame(series).sort_index()
        data["cash"] = 0.0
        value["attribution"] = attribution(plan, data)
        data.to_csv(root / "net_returns.csv")
        value["returns_sha256"] = file_hash(root / "net_returns.csv")
    dump(root / "paired-evidence.json", value)
    return root / "paired-evidence.json"


@pytest.fixture
def evidence(tmp_path):
    return make_paired(tmp_path / "first")


def pin(path):
    return path, file_hash(path)


def test_complete_native_chain_charts_and_sidecars_preserve_sources(evidence, tmp_path):
    second = make_paired(tmp_path / "second", offset=7)
    before = {
        p: (file_hash(p), p.stat().st_mtime_ns)
        for root in (evidence.parent, second.parent)
        for p in root.rglob("*")
        if p.is_file()
    }
    out, snapshot = write_dashboard_bundle(
        [], tmp_path / "report/index.html", paired_evidence=[pin(second), pin(evidence)]
    )
    paired = snapshot["paired_research"]
    assert paired["combined"]["sessions"] == 8
    assert paired["combined"]["boundaries"] == [4]
    assert paired["combined"]["metrics"]["base"]["net_return"] == pytest.approx(1.031**2 - 1)
    assert paired["combined"]["decompositions"]["cash"]["return_gap"] == pytest.approx(1 - 1.031**2)
    assert paired["combined"]["metrics"]["base"]["max_drawdown"] == 0
    html = out.read_text(encoding="utf-8")
    for text in (
        "反事实与基准",
        "累计净收益曲线",
        "回撤曲线",
        "残差",
        "独立账户",
        "synthetic-fixture",
    ):
        assert text in html
    assert html.count('data-reference="cash"') == 3
    sidecars = write_runtime_sidecars(snapshot, out)
    exported = json.loads(out.with_suffix(".paired.json").read_text(encoding="utf-8"))
    assert exported["schema_version"] == "quant-report-hub.paired-comparison/v1"
    assert exported["combined"] == paired["combined"]
    allowed = published_files(snapshot, out, sidecars)
    assert evidence.resolve() not in allowed
    assert out.with_suffix(".paired.json") in allowed
    assert before == {p: (file_hash(p), p.stat().st_mtime_ns) for p in before}
    outputs = write_daily_package(snapshot, tmp_path / "daily", include_pdf=False)
    assert any(p.name == "index.paired.json" for p in outputs)
    with pytest.raises(ValueError, match="outside paired"):
        write_dashboard_bundle([], evidence.parent / "report.html", paired_evidence=[pin(evidence)])
    with pytest.raises(ValueError, match="outside paired"):
        write_daily_package(snapshot, evidence.parent / "daily", include_pdf=False)
    assert not (evidence.parent / "daily").exists()
    assert "三个基准的实际定义" in html and "佣金、最低费用、税费及成交滑点乘数" in html
    assert "账本执行上限为4只，单只权重上限20%" in html
    assert "最多2只" not in html
    assert "paired-only" in html and "-0.0000%" not in html


def test_incomplete_fold_cannot_be_omitted_from_aggregate(evidence, tmp_path):
    failed = make_paired(tmp_path / "failed", offset=7, failure="fees")
    out, snapshot = write_dashboard_bundle(
        [], tmp_path / "index.html", paired_evidence=[pin(evidence), pin(failed)]
    )
    paired = snapshot["paired_research"]
    assert paired["combined"] is None and "整体汇总不可用" in paired["aggregation_error"]
    assert paired["folds"][1]["verified"] and not paired["folds"][1]["available"]
    assert paired["folds"][1]["reason"] == "fees：<missing price>"
    html = out.read_text(encoding="utf-8")
    assert "&lt;missing price&gt;" in html and "<missing price>" not in html
    assert "failed" in html
    assert "&lt;missing price&gt;" in html.split("<details")[0]
    assert "合成数据 · 仅验证软件" in html
    assert html.count("<h3>三个基准的实际定义</h3>") == 1
    assert "view" not in paired["folds"][1]


@pytest.mark.parametrize(
    "mutation",
    [
        "outer_hash",
        "plan",
        "inventory",
        "definition",
        "native",
        "native_mismatch",
        "matrix",
        "math",
        "omit_artifact",
        "escape",
        "available",
        "missing_candidate",
        "duplicate_candidate",
    ],
)
def test_tampering_never_renders_metrics(evidence, tmp_path, mutation):
    oldpin = pin(evidence)
    value = json.loads(evidence.read_text())
    root = evidence.parent
    if mutation == "outer_hash":
        value["reason"] = "changed"
    elif mutation == "plan":
        p = json.loads((root / "preregistration.json").read_text())
        p["plan"]["base"]["signal_delay"] = 3
        dump(root / "preregistration.json", p)
        value["preregistration_sha256"] = file_hash(root / "preregistration.json")
    elif mutation == "inventory":
        dump(root / "attempts.json", [])
    elif mutation == "definition":
        d = json.loads((root / "base/execution-definition.json").read_text())
        d["recipe"]["risk"] = {}
        dump(root / "base/execution-definition.json", d)
        value["attempts"][0]["definition_sha256"] = file_hash(
            root / "base/execution-definition.json"
        )
        dump(root / "attempts.json", value["attempts"])
    elif mutation == "native":
        path = root / "base/standard/v2/returns.parquet"
        path.write_bytes(path.read_bytes() + b"tampered")
    elif mutation == "native_mismatch":
        path = root / "base/returns.csv"
        frame = pd.read_csv(path, index_col=0)
        frame.iloc[0, 0] = 0.5
        frame.to_csv(path)
        result = json.loads((root / "base/result.json").read_text())
        result["artifacts"]["returns.csv"] = file_hash(path)
        dump(root / "base/result.json", result)
        value["attempts"][0]["result_sha256"] = file_hash(root / "base/result.json")
        dump(root / "attempts.json", value["attempts"])
    elif mutation == "matrix":
        path = root / "net_returns.csv"
        frame = pd.read_csv(path, index_col=0)
        frame.loc[frame.index[0], "cash"] = 0.01
        frame.to_csv(path)
        value["returns_sha256"] = file_hash(path)
    elif mutation == "math":
        value["attribution"]["return_gap"] += 0.01
    elif mutation in {"omit_artifact", "escape"}:
        path = root / "base/result.json"
        result = json.loads(path.read_text())
        if mutation == "omit_artifact":
            result["artifacts"].pop("returns.csv")
        else:
            result["artifacts"]["../../outside.json"] = "0" * 64
        dump(path, result)
        value["attempts"][0]["result_sha256"] = file_hash(path)
        dump(root / "attempts.json", value["attempts"])
    elif mutation == "available":
        value["available"] = False
    else:
        if mutation == "missing_candidate":
            value["attempts"].pop()
        else:
            value["attempts"].append(value["attempts"][0])
        dump(root / "attempts.json", value["attempts"])
    dump(evidence, value)
    sources = [oldpin if mutation == "outer_hash" else pin(evidence)]
    result = paired_snapshot(sources)
    fold = result["folds"][0]
    assert not fold["verified"] and not fold["available"] and "view" not in fold
    assert fold["reason"]


@pytest.mark.parametrize("change", ["overlap", "different_recipe", "duplicate"])
def test_incompatible_or_duplicate_folds_cannot_be_compounded(evidence, tmp_path, change):
    second = make_paired(
        tmp_path / "second",
        offset=0 if change == "overlap" else 7,
        hypothesis="other" if change == "different_recipe" else "fixture",
    )
    sources = [pin(evidence), pin(evidence if change == "duplicate" else second)]
    if change == "duplicate":
        with pytest.raises(ValueError, match="Duplicate"):
            paired_snapshot(sources)
    else:
        result = paired_snapshot(sources)
        assert result["combined"] is None and result["aggregation_error"]
        assert all(f["available"] for f in result["folds"])


def test_cli_paired_only_and_missing_source_are_explicit(evidence, tmp_path):
    out = tmp_path / "report/index.html"
    assert (
        main(
            [
                "dashboard",
                "--paired-evidence",
                str(evidence),
                file_hash(evidence),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert out.exists() and out.with_suffix(".paired.json").exists()
    missing = tmp_path / "absent/paired-evidence.json"
    result = paired_snapshot([(missing, "0" * 64)])
    assert not result["folds"][0]["verified"]
    with pytest.raises(SystemExit):
        main(["dashboard", "--out", str(out)])


def test_watcher_detects_changed_nested_artifact_and_replaces_valid_snapshot(evidence, tmp_path):
    sources = [pin(evidence)]
    before = source_fingerprint([], None, paired_evidence=sources)
    out = tmp_path / "index.html"
    _, first = write_dashboard_bundle([], out, paired_evidence=sources)
    assert first["paired_research"]["folds"][0]["available"]
    (evidence.parent / "base/returns.csv").write_text("changed", encoding="utf-8")
    assert source_fingerprint([], None, paired_evidence=sources) != before
    _, after = write_dashboard_bundle([], out, paired_evidence=sources)
    assert not after["paired_research"]["folds"][0]["available"]
    assert 'data-paired-view="' not in out.read_text(encoding="utf-8")


def test_explicit_null_removes_inherited_risk_model(tmp_path):
    source = make_paired(tmp_path / "risk", risk_model=True)
    assert load_paired(*pin(source))["available"]


def test_drawdown_includes_initial_capital_and_full_loss(evidence):
    plan = json.loads((evidence.parent / "preregistration.json").read_text())["plan"]
    data = pd.DataFrame(
        0.0,
        index=pd.date_range("2025-01-01", periods=4),
        columns=["base", *plan["variants"], *plan["benchmarks"]],
    )
    data.loc[data.index[0], "base"] = -0.1
    data.loc[data.index[1], "base"] = -1.0
    view = _view(data, plan, title="initial loss")
    assert view["curves"]["base"]["drawdown"] == pytest.approx([0.0, -0.1, -1.0, -1.0, -1.0])
    assert view["metrics"]["base"] == {"net_return": -1.0, "max_drawdown": -1.0}
