"""Read-only, fail-closed inputs for the research dashboard.

Decisions remain producer-owned. The report checks their contract and referenced
ledger, but never promotes a paper decision to an investment recommendation.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from quant_lab.contracts_v2 import RunManifestV2, load_and_validate_standard_run

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_RUNS = 200
STATUSES = {"blocked", "observe", "paper_ready"}


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path.name}")
    value = json.loads(
        path.read_text(encoding="utf-8"), parse_constant=_reject_constant, parse_float=_finite_float
    )
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path.name}")
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError("Expected timezone-aware timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return result


def _number(value: Any, *, minimum: float | None = None) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and (minimum is None or value >= minimum)
    )


def validate_decision(card: dict, run_id: str, now: datetime) -> None:
    required = {
        "schema_version",
        "run_id",
        "status",
        "as_of",
        "generated_at",
        "valid_until",
        "scope",
        "data_quality",
        "validation",
        "current_positions",
        "targets",
        "proposed_trades",
        "estimated_cost",
        "risk",
        "evidence",
        "reasons",
    }
    if required - card.keys():
        raise ValueError(f"Missing decision fields: {sorted(required - card.keys())}")
    if card.get("schema_version") != "quant.decision/v1":
        raise ValueError("Unsupported decision schema")
    if card.get("run_id") != run_id or card.get("status") not in STATUSES:
        raise ValueError("Decision run identity or status is invalid")
    if card.get("scope") != "paper_simulation_only":
        raise ValueError("Only paper_simulation_only decisions are supported")
    for key in ("data_quality", "validation", "estimated_cost", "risk", "evidence"):
        if not isinstance(card.get(key), dict):
            raise TypeError(f"Expected decision object: {key}")
    for key in ("current_positions", "targets", "proposed_trades"):
        rows = card.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"Expected decision rows: {key}")
    reasons = card.get("reasons")
    if not isinstance(reasons, list) or any(not isinstance(v, str) for v in reasons):
        raise ValueError("Expected string reasons")
    generated = timestamp(card.get("generated_at"))
    if generated > now:
        raise ValueError("Decision generation time is in the future")
    if card["status"] != "blocked":
        as_of = date.fromisoformat(card["as_of"])
        if as_of > generated.date():
            raise ValueError("Market date is after generation date")
        timestamp(card.get("valid_until"))
    if card["status"] != "paper_ready":
        if card["targets"] or card["proposed_trades"]:
            raise ValueError("Blocked/observe decision contains proposed trades or targets")
        return
    if any(card[key].get("passed") is not True for key in ("data_quality", "validation")):
        raise ValueError("Paper decision did not pass producer checks")
    if timestamp(card["valid_until"]) <= generated:
        raise ValueError("Paper decision was expired at generation")
    for key in ("targets", "proposed_trades"):
        for row in card[key]:
            if not isinstance(row.get("symbol"), str) or not row["symbol"]:
                raise ValueError("Missing proposed instrument")
            if not _number(row.get("quantity"), minimum=0) or row["quantity"] == 0:
                raise ValueError("Invalid proposed quantity")
            if key == "proposed_trades" and (
                row.get("side") not in {"buy", "sell"}
                or not isinstance(row.get("order_id"), str)
                or not row["order_id"]
            ):
                raise ValueError("Invalid proposed order identity or side")
    if any(
        not _number(card["estimated_cost"].get(k), minimum=0) for k in ("fees", "slippage", "total")
    ):
        raise ValueError("Invalid estimated cost")


def _verify_ledger(card: dict, run: Path) -> None:
    expected = (run / "standard" / "v2" / "run_manifest.json").resolve()
    evidence = card["evidence"]
    reference = Path(evidence.get("standard_manifest", ""))
    reference = reference if reference.is_absolute() else run / reference
    if reference.resolve() != expected or not expected.is_relative_to(run.resolve()):
        raise ValueError("Ledger reference must belong to this decision run")
    if hashlib.sha256(expected.read_bytes()).hexdigest() != evidence.get(
        "standard_manifest_sha256"
    ):
        raise ValueError("Ledger manifest hash mismatch")
    manifest = load_and_validate_standard_run(run)
    if not isinstance(manifest, RunManifestV2) or manifest.run_id != card["run_id"]:
        raise ValueError("Ledger identity does not match decision")
    if manifest.code_version != evidence.get("code_version"):
        raise ValueError("Ledger code version does not match decision")


def load_decision(path: Path, *, root: Path, now: datetime, latest: bool = False) -> dict:
    result = {
        "root": str(root),
        "run_id": path.parent.name,
        "path": str(path),
        "latest": latest,
        "status": "invalid",
        "card": {},
        "error": "",
    }
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Decision path escapes its configured root")
        card = read_json(path)
        validate_decision(card, path.parent.name, now)
        if card["status"] == "paper_ready" or card["evidence"].get("standard_manifest"):
            _verify_ledger(card, path.parent)
        result["card"] = card
        result["status"] = card["status"]
        if card["status"] != "blocked" and timestamp(card["valid_until"]) <= now:
            result["status"] = "expired"
    except Exception as exc:  # noqa: BLE001 -- isolate external artifact failures in the report
        # Each bad source becomes an explicit unavailable panel. Other configured
        # projects remain readable, and no earlier successful run is substituted.
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def load_decision_root(root: Path, now: datetime) -> dict:
    root = root.resolve()
    current = {
        "root": str(root),
        "run_id": "—",
        "path": "",
        "latest": True,
        "status": "invalid",
        "card": {},
        "error": "",
    }
    selected: Path | None = None
    try:
        pointer = read_json(root / "latest.json")
        run_id = pointer.get("run_id")
        if (
            not isinstance(run_id, str)
            or not run_id
            or Path(run_id).name != run_id
            or run_id in {".", ".."}
        ):
            raise ValueError("Invalid latest run identity")
        expected = root / run_id / "decision.json"
        target = Path(pointer["decision"])
        target = target if target.is_absolute() else root / target
        if target.resolve() != expected.resolve():
            raise ValueError("Latest decision path does not match run identity")
        selected = expected
        current = load_decision(expected, root=root, now=now, latest=True)
        if current["card"] and pointer.get("status") != current["card"]["status"]:
            raise ValueError("Latest pointer status disagrees with decision")
    except Exception as exc:  # noqa: BLE001 -- invalid latest must replace a formerly usable card
        current.update(status="invalid", card={}, error=f"{type(exc).__name__}: {exc}")
    candidates = sorted(root.glob("*/decision.json"), reverse=True) if root.is_dir() else []
    history_paths = [p for p in candidates if p != selected][:MAX_RUNS]
    history = [load_decision(p, root=root, now=now) for p in history_paths]
    return {
        "root": str(root),
        "current": current,
        "history": history,
        "omitted": max(0, len(candidates) - (selected in candidates) - MAX_RUNS),
    }


def read_experiments(db: Path | None, limit: int = MAX_RUNS) -> tuple[list[dict], str]:
    """Consume quant-lab's index without its mutating ExperimentStore constructor."""
    if db is None:
        return [], "未连接实验索引，可通过 --lab-db 指定 quant-lab SQLite 文件。"
    try:
        uri = db.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            records = connection.execute(
                "SELECT project, run_id, run_path, run_type, metrics_json, scanned_at "
                "FROM experiments ORDER BY scanned_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        rows = []
        for record in records:
            row = dict(record)
            row["error"] = ""
            row["verified"] = False
            try:
                run = Path(row["run_path"])
                # Index metrics are only a cache. A present standard artifact must
                # validate before its metrics can be displayed, with no fallback.
                if (run / "standard").exists():
                    manifest = load_and_validate_standard_run(run)
                    if manifest.run_id != row["run_id"] or manifest.project != row["project"]:
                        raise ValueError("Experiment index identity does not match source")
                    base = (
                        run / "standard" / "v2"
                        if isinstance(manifest, RunManifestV2)
                        else run / "standard"
                    )
                    row["metrics"] = read_json(base / "metrics.json")
                    row["verified"] = True
                elif not run.is_dir() or row["run_type"].startswith("standard"):
                    raise ValueError("Indexed source artifacts are missing")
                else:
                    row["metrics"] = json.loads(
                        row["metrics_json"],
                        parse_constant=_reject_constant,
                        parse_float=_finite_float,
                    )
                    if not isinstance(row["metrics"], dict):
                        raise ValueError("Invalid cached experiment metrics")
            except Exception as exc:  # noqa: BLE001 -- isolate independently indexed artifacts
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["metrics"] = {}
            row.pop("metrics_json")
            rows.append(row)
        return rows, ""
    except (OSError, sqlite3.Error) as exc:
        return [], f"实验索引不可用：{exc}"


def dashboard_snapshot(roots: list[Path], db: Path | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Dashboard time must include timezone")
    experiments, notice = read_experiments(db)
    return {
        "generated_at": now.isoformat(),
        "sources": [load_decision_root(root, now) for root in dict.fromkeys(roots)],
        "experiments": experiments,
        "index_notice": notice,
    }
