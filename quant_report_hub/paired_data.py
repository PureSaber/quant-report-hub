"""Verify native paired equity evidence before exposing descriptive comparisons."""

from __future__ import annotations

import json
from copy import deepcopy
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd
from quant_lab.contracts_v2 import RunManifestV2, load_and_validate_standard_run
from quant_lab.counterfactuals import BENCHMARKS, attribution, validate_plan
from quant_lab.research import digest, file_hash, verify_result
from quant_lab.selection import matrix

from quant_report_hub.dashboard_data import read_json


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Paired artifact escapes its source directory")
    return path


def _csv(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path, index_col=0, parse_dates=True, float_precision="round_trip")
    data = matrix(data)
    if data.index.tz is not None or not data.index.equals(data.index.normalize()):
        raise ValueError("Paired equity returns require daily local trading dates")
    if (data < -1).any().any():
        raise ValueError("Net return is below total loss")
    return data


def _same_numbers(actual, expected):
    """Only tolerate serialization roundoff, never missing keys or dates."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_same_numbers(actual[k], v) for k, v in expected.items())
        )
    if isinstance(expected, float):
        return (
            type(actual) in (float, int)
            and np.isfinite(actual)
            and np.isclose(actual, expected, rtol=0, atol=1e-12)
        )
    return actual == expected


def _definition(recipe, request, name):
    spec = deepcopy(recipe)
    spec["risk"] = deepcopy(request.get("risk", recipe.get("risk", {})))
    if "risk_model" in request:
        if request["risk_model"] is None:
            spec.pop("risk_model", None)
        else:
            spec["risk_model"] = deepcopy(request["risk_model"])
    candidate = {k: deepcopy(v) for k, v in request.items() if k not in {"risk", "risk_model"}}
    candidate.pop("candidate_id", None)
    candidate["name"] = name
    candidate["candidate_id"] = digest(candidate)[:20]
    return {"recipe": spec, "candidate": candidate}


def _run(root, recipe, request, attempt):
    name = attempt["name"]
    run = _inside(root, name)
    definition = _inside(run, "execution-definition.json")
    if file_hash(definition) != attempt["definition_sha256"]:
        raise ValueError("Execution definition hash mismatch")
    if read_json(definition) != _definition(recipe, request, name):
        raise ValueError("Execution definition differs from the paired plan")
    result = verify_result(_inside(run, "result.json"), attempt["result_sha256"])
    required = {"returns.csv", "execution-definition.json", "standard/v2/run_manifest.json"}
    if not required.issubset(result["artifacts"]):
        raise ValueError("Paired result does not bind required execution artifacts")
    manifest = load_and_validate_standard_run(run)
    if (
        not isinstance(manifest, RunManifestV2)
        or manifest.profile != "backtest-ledger"
        or manifest.project != "a-share-multifactor"
        or manifest.run_id != name
    ):
        raise ValueError("Paired equity comparison requires its own native v2 backtest ledger")
    for artifact in manifest.artifacts:
        if result["artifacts"].get("standard/v2/" + artifact.path) != artifact.sha256:
            raise ValueError("Paired result does not bind the complete v2 ledger")
    values = _csv(_inside(run, "returns.csv"))
    if list(values) != ["net_return"]:
        raise ValueError("One native net_return column is required")
    native = pd.read_parquet(_inside(run, "standard/v2/returns.parquet"))
    if native.strategy_id.nunique() != 1 or set(native.base_currency) != {manifest.base_currency}:
        raise ValueError("Paired returns require one strategy and one currency")
    dates = pd.DatetimeIndex(native.event_time).tz_convert("Asia/Shanghai").tz_localize(None)
    native_values = pd.Series(native.net_return.to_numpy(), index=dates.normalize())
    pd.testing.assert_series_equal(
        values.iloc[:, 0],
        native_values,
        check_names=False,
        check_freq=False,
        check_exact=False,
        rtol=0,
        atol=1e-12,
    )
    comparison = result["comparison"]
    if comparison["currency"] != manifest.base_currency or any(
        comparison[key] != recipe["interval"][key] for key in ("start", "end")
    ):
        raise ValueError("Paired result interval or currency differs from its definition")
    if values.index.min() < pd.Timestamp(comparison["start"]) or values.index.max() > pd.Timestamp(
        comparison["end"]
    ):
        raise ValueError("Paired return dates escape the declared interval")
    config = read_json(_inside(run, "standard/v2/config.json"))
    limits = {
        k: config.get("costs", {}).get(k)
        for k in ("max_holdings", "max_position_weight", "cash_buffer")
    }
    return (
        values.iloc[:, 0],
        {
            "currency": manifest.base_currency,
            "scope": result["scope"],
            "code_version": manifest.code_version,
            "execution_model_version": manifest.execution_model_version,
        },
        limits,
    )


def _view(data, plan, *, title, boundaries=()):
    curves, metrics = {}, {}
    for name in data:
        nav = np.r_[1.0, (1 + data[name]).cumprod().to_numpy()]
        drawdown = nav / np.maximum.accumulate(nav) - 1
        curves[name] = {"cumulative": (nav - 1).tolist(), "drawdown": drawdown.tolist()}
        metrics[name] = {"net_return": float(nav[-1] - 1), "max_drawdown": float(drawdown.min())}
    return {
        "title": title,
        "sessions": len(data),
        "start": data.index[0].date().isoformat(),
        "end": data.index[-1].date().isoformat(),
        "dates": ["期初", *data.index.strftime("%Y-%m-%d")],
        "curves": curves,
        "metrics": metrics,
        "boundaries": list(boundaries),
        "decompositions": {
            name: attribution(plan, data, reference=name) for name in sorted(BENCHMARKS)
        },
    }


def load_paired(source: Path, expected_sha256: str) -> dict:
    """Check the caller-pinned evidence and its entire native artifact chain."""
    source = source.resolve()
    if file_hash(source) != expected_sha256:
        raise ValueError("Paired evidence snapshot hash mismatch")
    value = read_json(source)
    if (
        value.get("schema") != "quant.paired-evidence/v1"
        or type(value.get("available")) is not bool
    ):
        raise ValueError("Unsupported paired evidence schema or availability")
    root = source.parent
    preregistration = _inside(root, "preregistration.json")
    if file_hash(preregistration) != value["preregistration_sha256"]:
        raise ValueError("Paired preregistration hash mismatch")
    frozen = read_json(preregistration)
    plan = validate_plan(frozen["plan"])
    recipe = frozen["recipe"]
    if recipe["backend"] != "equity" or recipe.get("validation"):
        raise ValueError("Paired evidence must describe an independent single equity interval")
    if value["plan_sha256"] != plan["sha256"]:
        raise ValueError("Paired evidence plan hash mismatch")
    if plan["benchmarks"]["cash"] != {"mode": "cash", "daily_return": 0}:
        raise ValueError("Cash benchmark must explicitly be zero-interest native cash")
    attempts = value["attempts"]
    if json.loads(_inside(root, "attempts.json").read_text(encoding="utf-8")) != attempts:
        raise ValueError("Paired attempt inventory differs from the pinned evidence")
    requests = {"base": plan["base"], **plan["variants"], **plan["benchmarks"]}
    expected = set(requests) - {"cash"}
    names = [a["name"] for a in attempts]
    if len(names) != len(set(names)) or set(names) - expected:
        raise ValueError("Duplicate or unknown paired attempt")
    series, contexts, execution_limits = {}, [], {}
    for attempt in attempts:
        if attempt["status"] not in {"completed", "failed"}:
            raise ValueError("Unknown paired attempt status")
        if attempt["status"] == "completed":
            values, context, limits = _run(root, recipe, requests[attempt["name"]], attempt)
            series[attempt["name"]] = values
            contexts.append(context)
            execution_limits[attempt["name"]] = limits
    if contexts and any(c != contexts[0] for c in contexts):
        raise ValueError("Paired candidates have incompatible currency or data scope")
    result = {
        "title": recipe["study_id"],
        "source": str(source),
        "sha256": expected_sha256,
        "verified": True,
        "available": value["available"],
        "reason": value.get("reason", ""),
        "attempts": [
            *attempts,
            *({"name": n, "status": "missing"} for n in sorted(expected - set(names))),
        ],
        "plan": plan,
        "recipe": recipe,
        "input_manifest_sha256": frozen["input_manifest_sha256"],
        "context": contexts[0] if contexts else {},
        "execution_limits": execution_limits,
    }
    if not value["available"]:
        if "attribution" in value or "returns_sha256" in value:
            raise ValueError("Unavailable paired evidence cannot expose a complete decomposition")
        if not result["reason"]:
            result["reason"] = "；".join(
                f"{a['name']}：{a.get('error') or a['status']}"
                for a in result["attempts"]
                if a["status"] != "completed"
            )
        return result
    if set(series) != expected:
        raise ValueError("Available paired evidence omits or fails planned candidates")
    returns_path = _inside(root, "net_returns.csv")
    if file_hash(returns_path) != value["returns_sha256"]:
        raise ValueError("Paired return matrix hash mismatch")
    actual = pd.DataFrame(series).sort_index()
    actual["cash"] = 0.0
    actual = matrix(actual)
    pd.testing.assert_frame_equal(
        _csv(returns_path),
        actual,
        check_names=False,
        check_freq=False,
        check_exact=False,
        rtol=0,
        atol=1e-12,
    )
    verified = attribution(plan, actual, reference=value["attribution"]["reference"])
    if not _same_numbers(value["attribution"], verified):
        raise ValueError("Paired attribution differs from native net returns")
    result["view"] = _view(actual, plan, title=recipe["study_id"])
    result["_returns"] = actual
    return result


def paired_snapshot(sources: list[tuple[Path, str]]) -> dict:
    """Keep failed folds visible; never combine only a successful subset."""
    if len({Path(p).resolve() for p, _ in sources}) != len(sources):
        raise ValueError("Duplicate paired evidence source")
    folds = []
    for path, sha in sources:
        try:
            fold = load_paired(Path(path), sha)
        except (OSError, ValueError, TypeError, KeyError, AssertionError) as exc:
            fold = {
                "title": Path(path).parent.name,
                "source": str(Path(path).resolve()),
                "sha256": sha,
                "verified": False,
                "available": False,
                "reason": f"{type(exc).__name__}: {exc}",
                "attempts": [],
            }
        folds.append(fold)
    result = {"folds": folds, "combined": None, "aggregation_error": ""}
    if len(folds) > 1:
        try:
            if not all(fold["available"] for fold in folds):
                raise ValueError("存在未完成或未通过核验的折；整体汇总不可用。")
            first = folds[0]
            basis = lambda f: (
                f["plan"],
                f["context"],
                f["input_manifest_sha256"],
                f["execution_limits"],
                {k: v for k, v in f["recipe"].items() if k not in {"study_id", "interval"}},
            )
            if any(basis(f) != basis(first) for f in folds[1:]):
                raise ValueError("各折计划、来源、币种或配方不同；仅可逐折查看。")
            ordered = sorted(folds, key=lambda f: f["_returns"].index[0])
            for left, right in pairwise(ordered):
                if pd.Timestamp(left["recipe"]["interval"]["end"]) >= pd.Timestamp(
                    right["recipe"]["interval"]["start"]
                ):
                    raise ValueError("测试区间重叠；不能重复复合同一市场日期。")
            lengths = np.cumsum([len(f["_returns"]) for f in ordered[:-1]]).tolist()
            data = matrix(pd.concat([f["_returns"] for f in ordered]))
            result["combined"] = _view(
                data, first["plan"], title="各折复合序列", boundaries=lengths
            )
        except ValueError as exc:
            result["aggregation_error"] = str(exc)
    for fold in folds:
        fold.pop("_returns", None)
    return result
