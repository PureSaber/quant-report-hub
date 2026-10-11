"""Cross-asset portfolio accounting bridges with explicit evidence levels.

Native cash accounts reuse the existing complete ledger reconstruction. Other
asset results remain externally reported components or an unallocated NAV bridge.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

import numpy as np
import pandas as pd

from quant_report_hub.attribution import (
    _decimal_from_fixed,
    _read_validated_v2,
    _reconstruct_standard_run_v2,
)
from quant_report_hub.cash_attribution import _reconstruct

ZERO = Decimal(0)
LEVELS = {"nav_bridge", "reported_components", "native_cash_ledger", "validated_v2_components"}
NATIVE_LEVELS = {"native_cash_ledger", "validated_v2_components"}
RESERVED = {"residual", "fx_on_opening_nav", "fx_on_flows"}


def _number(value, *, positive=False):
    if not isinstance(value, str):
        raise TypeError("amounts and FX must be decimal strings")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal amount") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError("invalid finite amount or positive FX rate")
    return result


def _time(value):
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return result.tz_convert("UTC")


def _text(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("identities, labels and source refs must be nonblank strings")
    return value


def _native_periods(account, root):
    source, manifest, frames, fingerprint = _read_validated_v2(root / account["run_dir"])
    if fingerprint != account["run_manifest_sha256"]:
        raise ValueError("native run manifest hash mismatch")
    tables, summary = _reconstruct(manifest, frames)
    if summary["currency"] != account["currency"]:
        raise ValueError("native currency mismatch")
    source_rows = tables["period_reconciliation.csv"].to_dict("records")
    supplied = account["periods"]
    if len(supplied) != len(source_rows):
        raise ValueError("native adapter requires all source return periods")
    rows = []
    for fields, native in zip(supplied, source_rows):
        if _time(fields["end"]) != _time(native["event_time"]):
            raise ValueError("native period boundary mismatch")
        if _time(fields["known_at"]) < _time(manifest.created_at):
            raise ValueError("native accounting report cannot predate run creation")
        row = dict(fields)
        row.update(
            opening_nav=str(native["opening_nav"]),
            closing_nav=str(native["closing_nav"]),
            flows=[],
            components={
                k: str(native[k])
                for k in ("valuation_and_trading_pnl", "corporate_income", "fee_cash")
            },
        )
        rows.append(row)
    if _time(supplied[0]["start"]) > frames["cash_ledger"]["event_time"].min():
        raise ValueError("native opening boundary excludes ledger events")
    return rows, {
        "run_dir": str(source.resolve()),
        "run_manifest_sha256": fingerprint,
        "native_account_id": summary["account_id"],
        "summary": summary,
    }


def _v2_periods(account, root):
    references = None
    if "slippage_references" in account:
        path = root / account["slippage_references"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != account["slippage_references_sha256"]:
            raise ValueError("slippage reference hash mismatch")
        references = pd.read_csv(io.BytesIO(raw), dtype={"fill_id": str, "instrument_id": str})
    source, manifest, frames, detail, reconciliation, _, fingerprint = _reconstruct_standard_run_v2(
        root / account["run_dir"], slippage_references=references
    )
    if (
        fingerprint != account["run_manifest_sha256"]
        or account["currency"] != manifest.base_currency
    ):
        raise ValueError("v2 source hash or currency mismatch")
    snapshots = frames["portfolio_snapshots"].sort_values("event_time")
    if snapshots.account_id.nunique() != 1:
        raise ValueError("one v2 account per portfolio sleeve is required")
    records = snapshots.to_dict("records")
    for record in detail.to_dict("records"):
        if (
            _time(record["event_time"]) <= _time(records[0]["event_time"])
            and _decimal_from_fixed(
                record["base_amount_units"], record["base_amount_scale"], "base amount"
            )
            != 0
        ):
            raise ValueError("v2 component precedes the first attributable interval")
    supplied = account["periods"]
    if len(records) < 2 or len(supplied) != len(records) - 1:
        raise ValueError("v2 adapter requires every adjacent snapshot interval")
    rows = []
    for i, fields in enumerate(supplied):
        before, after = records[i : i + 2]
        if (
            _time(fields["start"]) != _time(before["event_time"])
            or _time(fields["end"]) != _time(after["event_time"])
            or _time(fields["known_at"]) < _time(manifest.created_at)
        ):
            raise ValueError("v2 period/publication boundary mismatch")
        components = defaultdict(lambda: ZERO)
        for record in detail.to_dict("records"):
            if (
                _time(before["event_time"])
                < _time(record["event_time"])
                <= _time(after["event_time"])
            ):
                key = (
                    "source_residual" if record["component"] == "residual" else record["component"]
                )
                components[key] += _decimal_from_fixed(
                    record["base_amount_units"], record["base_amount_scale"], "base amount"
                )
        rows.append(
            dict(
                fields,
                flows=[],
                components={k: str(v) for k, v in components.items()},
                opening_nav=str(
                    _decimal_from_fixed(before["nav_units"], before["nav_scale"], "NAV")
                ),
                closing_nav=str(_decimal_from_fixed(after["nav_units"], after["nav_scale"], "NAV")),
            )
        )
    return rows, {
        "run_dir": str(source.resolve()),
        "run_manifest_sha256": fingerprint,
        "native_account_id": str(records[0]["account_id"]),
        "reconciliation_rows": len(reconciliation),
        "scope": "existing M5 component/cost/NAV checks; source non-cost P&L is producer supplied",
    }


def _risk(model, rows, start, ids):
    if model is None:
        return {"status": "unavailable", "reason": "no PIT covariance supplied"}
    if not _time(model["estimation_end"]) <= _time(model["known_at"]) <= start:
        raise ValueError("risk model must be estimated and known by period start")
    if model["accounts"] != ids or model["return_basis"] != "base_net_simple_total_return":
        raise ValueError("risk model axes or return basis mismatch")
    _text(model["source_ref"])
    _text(model["period_unit"])
    cov = np.array(model["covariance"], dtype=float)
    if cov.shape != (len(ids), len(ids)) or not np.isfinite(cov).all():
        raise ValueError("invalid risk covariance dimensions or finite values")
    if (
        not np.allclose(cov, cov.T, rtol=1e-12, atol=1e-14)
        or (cov.diagonal() < 0).any()
        or np.linalg.eigvalsh(cov).min() < -max(float(np.abs(cov).max()), 1e-300) * 1e-12
    ):
        raise ValueError("risk covariance must be symmetric PSD")
    opening = np.array([float(_number(r["opening_base"])) for r in rows])
    if (opening < 0).any() or opening.sum() <= 0:
        return {"status": "unavailable", "reason": "nonpositive or negative opening capital"}
    weights = opening / opening.sum()
    components = weights * (cov @ weights)
    variance = float(components.sum())
    if variance < 0:
        raise ValueError("risk model produces negative portfolio variance")
    return {
        "status": "model_based",
        "source_ref": model["source_ref"],
        "period_unit": model["period_unit"],
        "variance": variance,
        "variance_contributions": dict(zip(ids, components.tolist())),
        "volatility_contributions": (
            dict(zip(ids, (components / np.sqrt(variance)).tolist())) if variance > 0 else None
        ),
        "weights": dict(zip(ids, weights.tolist())),
    }


def evaluate_portfolio_attribution(spec, *, source_root=Path(".")):
    with localcontext() as context:
        context.prec = 80
        return _evaluate(spec, Path(source_root))


def _evaluate(spec, root):
    if spec["schema"] != "quant-report-hub.portfolio-attribution/v1":
        raise ValueError("unsupported portfolio attribution schema")
    as_of, base = _time(spec["evaluation_as_of"]), _text(spec["base_currency"])
    accounts = spec["accounts"]
    ids = [_text(a["id"]) for a in accounts]
    scopes = [_text(a["economic_scope"]) for a in accounts]
    if not ids or len(set(ids)) != len(ids) or len(set(scopes)) != len(scopes):
        raise ValueError("account identities and economic scopes must be unique and nonempty")
    detail, provenance, native_ids, all_periods, flow_pairs = [], {}, set(), None, defaultdict(list)
    for account in accounts:
        identity, currency, level = (
            account["id"],
            _text(account["currency"]),
            account["evidence_level"],
        )
        _text(account["asset_class"])
        _text(account["source_ref"])
        if level not in LEVELS:
            raise ValueError("unsupported evidence level")
        if account["data_nature"] not in {
            "synthetic",
            "retrospective",
            "historical_pit",
            "independent_forward",
        }:
            raise ValueError("unknown data_nature")
        if level in NATIVE_LEVELS:
            periods, receipt = (
                _native_periods(account, root)
                if level == "native_cash_ledger"
                else _v2_periods(account, root)
            )
            native_id = (receipt["run_manifest_sha256"], receipt["native_account_id"])
            if native_id in native_ids:
                raise ValueError("duplicate native economic source")
            native_ids.add(native_id)
        else:
            periods, receipt = account["periods"], {"source_ref": account["source_ref"]}
        provenance[identity] = dict(
            receipt, evidence_level=level, data_nature=account["data_nature"]
        )
        previous, keys, flow_ids = None, [], set()
        for raw in periods:
            start, end, known = (_time(raw[k]) for k in ("start", "end", "known_at"))
            if not start < end <= known <= as_of:
                raise ValueError("attribution requires start < end <= known_at <= evaluation_as_of")
            fx0, fx1 = (
                _number(raw["fx_start"], positive=True),
                _number(raw["fx_end"], positive=True),
            )
            if not start <= _time(raw["fx_start_known_at"]) <= as_of:
                raise ValueError("opening FX timing invalid")
            if not end <= _time(raw["fx_end_known_at"]) <= as_of:
                raise ValueError("closing FX timing invalid")
            if currency == base and (fx0 != 1 or fx1 != 1):
                raise ValueError("base-currency FX must be one")
            opening, closing = _number(raw["opening_nav"]), _number(raw["closing_nav"])
            if previous and (start != previous[0] or opening != previous[1] or fx0 != previous[2]):
                raise ValueError("non-contiguous NAV/FX/account period chain")
            previous = (end, closing, fx1)
            keys.append((start, end))
            local_flow, base_flow, external_flow, flow_fx = ZERO, ZERO, ZERO, ZERO
            for flow in raw["flows"]:
                flow_id = _text(flow["flow_id"])
                if flow_id in flow_ids:
                    raise ValueError("duplicate flow identity within account")
                flow_ids.add(flow_id)
                time, available = _time(flow["time"]), _time(flow["known_at"])
                if not start < time <= end or not time <= available <= as_of:
                    raise ValueError("flow outside period or unavailable")
                amount, rate = _number(flow["amount"]), _number(flow["fx_rate"], positive=True)
                if currency == base and rate != 1:
                    raise ValueError("base-currency flow FX must be one")
                if not time <= _time(flow["fx_known_at"]) <= as_of:
                    raise ValueError("flow FX unavailable")
                local_flow += amount
                base_flow += amount * rate
                flow_fx += amount * (fx1 - rate)
                if flow["kind"] == "external":
                    external_flow += amount * rate
                elif flow["kind"] == "internal_transfer":
                    flow_pairs[_text(flow["transfer_id"])].append((identity, time, amount * rate))
                else:
                    raise ValueError("unsupported flow classification")
            local_pnl = closing - opening - local_flow
            components = {_text(k): _number(v) for k, v in raw["components"].items()}
            if RESERVED.intersection(components) or (level == "nav_bridge" and components):
                raise ValueError("reserved components or unsupported precision for NAV bridge")
            residual = local_pnl - sum(components.values(), ZERO)
            if level == "native_cash_ledger" and residual != 0:
                raise ValueError("native cash components do not reconcile")
            base_components = {k: v * fx1 for k, v in components.items()}
            base_components.update(
                residual=residual * fx1,
                fx_on_opening_nav=opening * (fx1 - fx0),
                fx_on_flows=flow_fx,
            )
            opening_base, closing_base = opening * fx0, closing * fx1
            pnl_base = closing_base - opening_base - base_flow
            if sum(base_components.values(), ZERO) != pnl_base:
                raise ArithmeticError("portfolio FX/P&L bridge failed exact conservation")
            detail.append(
                {
                    "account": identity,
                    "asset_class": account["asset_class"],
                    "currency": currency,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "evidence_level": level,
                    "data_nature": account["data_nature"],
                    "opening_base": str(opening_base),
                    "closing_base": str(closing_base),
                    "net_flow_base": str(base_flow),
                    "external_flow_base": str(external_flow),
                    "pnl_base": str(pnl_base),
                    "flows_present": bool(raw["flows"]),
                    "local_residual": str(residual),
                    "components_base": {k: str(v) for k, v in base_components.items()},
                }
            )
        if not keys or (all_periods is not None and keys != all_periods):
            raise ValueError("all accounts must cover identical nonempty ordered periods")
        all_periods = keys
    for pairs in flow_pairs.values():
        if (
            len(pairs) != 2
            or pairs[0][0] == pairs[1][0]
            or pairs[0][1] != pairs[1][1]
            or pairs[0][2] + pairs[1][2] != 0
        ):
            raise ValueError(
                "internal transfer must pair across accounts at equal opposite base value"
            )
    models = {}
    for model in spec.get("risk_models", []):
        key = _time(model["period_start"])
        if key in models or key not in {p[0] for p in all_periods}:
            raise ValueError("risk model period duplicate or outside evaluation")
        models[key] = model
    aggregate = []
    for start, end in all_periods:
        rows = [r for r in detail if r["start"] == start.isoformat()]
        opening = sum((_number(r["opening_base"]) for r in rows), ZERO)
        closing = sum((_number(r["closing_base"]) for r in rows), ZERO)
        external = sum((_number(r["external_flow_base"]) for r in rows), ZERO)
        pnl = sum((_number(r["pnl_base"]) for r in rows), ZERO)
        totals = defaultdict(lambda: ZERO)
        for row in rows:
            for component, amount in row["components_base"].items():
                totals[component] += _number(amount)
        if closing - opening - external != pnl or sum(totals.values(), ZERO) != pnl:
            raise ArithmeticError("total portfolio conservation failed")
        has_flows = any(r["flows_present"] for r in rows)
        aggregate.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "opening_base": str(opening),
                "closing_base": str(closing),
                "external_flow_base": str(external),
                "pnl_base": str(pnl),
                "components_base": {k: str(v) for k, v in totals.items()},
                "pnl_over_opening_nav": str(pnl / opening) if opening > 0 else None,
                "return_interpretation": (
                    "flow_affected_ratio_not_TWR"
                    if has_flows
                    else "net_simple_return"
                    if opening > 0
                    else "unavailable"
                ),
                "account_contributions": {
                    r["account"]: str(_number(r["pnl_base"]) / opening) if opening > 0 else None
                    for r in rows
                },
                "risk_attribution": _risk(models.get(start), rows, start, ids),
            }
        )
    return {
        "schema": "quant-report-hub.portfolio-attribution-result/v1",
        "base_currency": base,
        "evaluation_as_of": as_of.isoformat(),
        "accounts": detail,
        "portfolio": aggregate,
        "sources": provenance,
        "precision_claim": "component evidence levels preserved per account",
        "limitations": [
            "NAV-only local P&L stays in residual; reported components are not transaction-verified.",
            "Native cash source verification covers its documented cash-ledger scope only.",
            "FX bridge translates local P&L at ending FX; cross terms stay in those translated amounts.",
            "FX on opening capital and external/internal flow timing is shown separately.",
            "Flow-affected P&L/opening NAV is not a time-weighted return.",
            "Risk is supplied-model Euler decomposition, not causal or realized trade attribution.",
            "No forward evidence or market authenticity is inferred from source hashes.",
        ],
    }


def _payloads(result, input_bytes):
    result = dict(result, input_sha256=hashlib.sha256(input_bytes).hexdigest())
    serialized = (
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["start", "end", "account", "evidence_level", "component", "amount_base"])
    for row in result["accounts"]:
        for component, value in row["components_base"].items():
            writer.writerow(
                [row["start"], row["end"], row["account"], row["evidence_level"], component, value]
            )
    cells = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(row[k]))}</td>"
            for k in ("end", "account", "evidence_level", "pnl_base", "local_residual")
        )
        + "</tr>"
        for row in result["accounts"]
    )
    page = (
        "<!doctype html><html lang='en'><meta charset='utf-8'><title>Portfolio attribution</title>"
        "<style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}"
        "table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;"
        "text-align:left}code{overflow-wrap:anywhere}</style><h1>Portfolio accounting bridge</h1>"
        f"<p>Base currency: {html.escape(result['base_currency'])}. Evidence precision is shown per account.</p>"
        "<table><thead><tr><th>Period end</th><th>Account</th><th>Evidence</th><th>Base P&amp;L</th>"
        "<th>Local residual</th></tr></thead><tbody>"
        + cells
        + "</tbody></table><ul>"
        + "".join(f"<li>{html.escape(line)}</li>" for line in result["limitations"])
        + "</ul><p><a href='result.json'>Full portfolio, risk and provenance JSON</a> · "
        "<a href='components.csv'>All signed component amounts</a></p></html>"
    )
    return {
        "input.json": input_bytes,
        "result.json": serialized,
        "components.csv": output.getvalue().encode(),
        "report.html": page.encode(),
    }


def run_report(input_path, output, *, verify=False):
    source, target = Path(input_path).resolve(), Path(output).resolve()
    raw = source.read_bytes()
    spec = json.loads(raw.decode("utf-8-sig"))
    for account in spec["accounts"]:
        if account["evidence_level"] in NATIVE_LEVELS:
            native = (source.parent / account["run_dir"]).resolve()
            if target == native or native in target.parents:
                raise ValueError("output must be outside native source run")
    result = evaluate_portfolio_attribution(spec, source_root=source.parent)
    payloads = _payloads(result, raw)
    manifest = {
        "schema": "quant-report-hub.portfolio-attribution-report/v1",
        "files": {k: hashlib.sha256(v).hexdigest() for k, v in payloads.items()},
    }
    payloads["manifest.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    if verify:
        if any((target / name).read_bytes() != payload for name, payload in payloads.items()):
            raise ValueError("report differs from independent source re-evaluation")
    else:
        target.mkdir(parents=True, exist_ok=False)
        for name, payload in payloads.items():
            (target / name).write_bytes(payload)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    run_report(args.input, args.out, verify=args.verify)


if __name__ == "__main__":
    main()
