"""Inspect a verified discrepancy resolution and its downstream invalidation list."""

import json
from pathlib import Path

from quant_data_kit.financial.reconciliation import digest


def resolution_card(path):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if record.get("schema") != "qdk.source-adjudication/1":
        raise ValueError("unsupported source resolution")
    if digest({k: v for k, v in record.items() if k != "snapshot_id"}) != record.get("snapshot_id"):
        raise ValueError("source resolution hash mismatch")
    case = record["case"]
    if digest({k: v for k, v in case.items() if k != "case_id"}) != case.get("case_id"):
        raise ValueError("source case hash mismatch")
    return {
        "snapshot_id": record["snapshot_id"],
        "prior_snapshot": record["prior_snapshot"],
        "instrument_id": case["instrument_id"],
        "field": case["field"],
        "reason": case["reason"],
        "selected": record["selected_observation_id"],
        "rationale": record["rationale"],
        "reviewer": record["reviewer"],
        "resolved_at": record["resolved_at"],
        "evidence_uri": record["evidence_uri"],
        "requires_rerun": record["impacted"],
        "status": "resolved_rerun_not_yet_verified",
    }
