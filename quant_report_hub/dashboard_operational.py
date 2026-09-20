"""Operational summaries derived from an already validated standard/v2 run.

The dashboard never mutates these artifacts.  This module deliberately keeps
decision intent, execution facts, and observed outcomes separate so an empty
fill set or an immature forward window is not presented as a successful trade.
"""

from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from quant_lab.contracts_v2 import ArtifactRecordV2, RunManifestV2

MAX_ACTION_ORDERS = 1_000
MAX_POSITION_ROWS = 50_000
MAX_RETURN_ROWS = 100_000
WINDOWS = (1, 5, 20)


def _artifact(manifest: RunManifestV2, name: str) -> ArtifactRecordV2 | None:
    return next((item for item in manifest.artifacts if item.name == name), None)


def _artifact_path(run: Path, artifact: ArtifactRecordV2) -> Path:
    base = (run / "standard" / "v2").resolve()
    path = (base / artifact.path).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Artifact path escapes standard/v2: {artifact.name}")
    return path


def _rows(
    run: Path,
    manifest: RunManifestV2,
    name: str,
    columns: list[str],
    *,
    filters: list[tuple[str, str, Any]] | None = None,
) -> list[dict]:
    artifact = _artifact(manifest, name)
    if artifact is None or artifact.rows == 0:
        return []
    missing = set(columns) - set(artifact.columns)
    if missing:
        raise ValueError(f"{name} is missing dashboard columns: {sorted(missing)}")
    return pq.read_table(
        _artifact_path(run, artifact), columns=columns, filters=filters
    ).to_pylist()


def _scaled(row: dict, units: str, scale: str) -> Decimal:
    raw_units = row.get(units)
    raw_scale = row.get(scale)
    if not isinstance(raw_units, int) or isinstance(raw_units, bool):
        raise TypeError(f"Invalid exact units: {units}")
    if not isinstance(raw_scale, int) or isinstance(raw_scale, bool):
        raise TypeError(f"Invalid exact scale: {scale}")
    if raw_scale < 0:
        raise ValueError(f"Negative exact scale: {scale}")
    return Decimal(raw_units).scaleb(-raw_scale)


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def run_identity(manifest: RunManifestV2) -> dict:
    """Return the small identity surface useful to a decision reviewer."""
    return {
        "project": manifest.project,
        "strategies": list(manifest.strategy_ids),
        "accounts": [],
        "profile": manifest.profile,
        "base_currency": manifest.base_currency,
        "config_sha256": manifest.config_sha256,
        "code_version": manifest.code_version,
        "execution_model_version": manifest.execution_model_version,
    }


def execution_summary(
    run: Path,
    manifest: RunManifestV2,
    card: dict,
    *,
    followup_runs: list[tuple[Path, RunManifestV2]] | None = None,
) -> dict:
    """Join proposed orders to validated facts from this and later account runs.

    Prospective paper orders are normally accepted in one decision run and
    filled by the next session's replay.  Later ledgers may contain cumulative
    copies of the same records, so stable identifiers are de-duplicated before
    totals are calculated.
    """
    proposed = card.get("proposed_trades", [])
    base = {
        "available": False,
        "notice": "本次决策没有拟调仓。",
        "planned_orders": len(proposed),
        "matched_orders": 0,
        "orders_with_fills": 0,
        "fill_records": 0,
        "actual_costs": [],
        "orders": [],
        "positions": [],
        "accounts": [],
        "evidence_runs": [],
    }
    if not proposed:
        return base
    if len(proposed) > MAX_ACTION_ORDERS:
        base["notice"] = f"拟调仓超过 {MAX_ACTION_ORDERS} 条，未加载逐单执行明细。"
        return base

    order_ids = [row["order_id"] for row in proposed]
    contexts = [(run, manifest), *(followup_runs or [])]
    order_rows: list[dict] = []
    fill_by_id: dict[str, dict] = {}
    cost_by_id: dict[str, dict] = {}
    for evidence_run, evidence_manifest in contexts:
        order_rows.extend(
            _rows(
                evidence_run,
                evidence_manifest,
                "orders",
                [
                    "event_time",
                    "order_id",
                    "account_id",
                    "instrument_id",
                    "side",
                    "quantity_units",
                    "quantity_scale",
                    "status",
                    "filled_quantity_units",
                    "filled_quantity_scale",
                    "version",
                ],
                filters=[("order_id", "in", order_ids)],
            )
        )
        for row in _rows(
            evidence_run,
            evidence_manifest,
            "fills",
            [
                "event_time",
                "fill_id",
                "order_id",
                "account_id",
                "instrument_id",
                "side",
                "quantity_units",
                "quantity_scale",
                "price_units",
                "price_scale",
                "currency",
            ],
            filters=[("order_id", "in", order_ids)],
        ):
            fill_by_id[row["fill_id"]] = row
    fill_rows = list(fill_by_id.values())
    fill_ids = list(fill_by_id)
    if fill_ids:
        for evidence_run, evidence_manifest in contexts:
            for row in _rows(
                evidence_run,
                evidence_manifest,
                "costs",
                [
                    "cost_id",
                    "fill_id",
                    "cost_type",
                    "amount_units",
                    "amount_scale",
                    "currency",
                ],
                filters=[("fill_id", "in", fill_ids)],
            ):
                cost_by_id[row["cost_id"]] = row
    cost_rows = list(cost_by_id.values())
    latest: dict[str, dict] = {}
    for row in order_rows:
        existing = latest.get(row["order_id"])
        if existing is None or (row["version"], row["event_time"]) > (
            existing["version"],
            existing["event_time"],
        ):
            latest[row["order_id"]] = row

    fills_by_order: dict[str, list[dict]] = {}
    order_for_fill: dict[str, str] = {}
    for row in fill_rows:
        fills_by_order.setdefault(row["order_id"], []).append(row)
        order_for_fill[row["fill_id"]] = row["order_id"]
    costs_by_order: dict[str, dict[str, Decimal]] = {}
    total_costs: dict[str, Decimal] = {}
    for row in cost_rows:
        order_id = order_for_fill.get(row["fill_id"])
        if order_id is None:
            continue
        amount = _scaled(row, "amount_units", "amount_scale")
        currency = row["currency"]
        costs_by_order.setdefault(order_id, {}).setdefault(currency, Decimal(0))
        costs_by_order[order_id][currency] += amount
        total_costs.setdefault(currency, Decimal(0))
        total_costs[currency] += amount

    details = []
    accounts: set[str] = set()
    orders_with_fills = 0
    mismatches: list[str] = []
    for intent in proposed:
        order_id = intent["order_id"]
        order = latest.get(order_id)
        fills = fills_by_order.get(order_id, [])
        filled = sum(
            (_scaled(row, "quantity_units", "quantity_scale") for row in fills), Decimal(0)
        )
        notional = sum(
            (
                _scaled(row, "quantity_units", "quantity_scale")
                * _scaled(row, "price_units", "price_scale")
                for row in fills
            ),
            Decimal(0),
        )
        average_price = notional / filled if filled else None
        if filled:
            orders_with_fills += 1
        planned = Decimal(str(intent["quantity"]))
        order_quantity = (
            _scaled(order, "quantity_units", "quantity_scale") if order is not None else None
        )
        source_filled = (
            _scaled(order, "filled_quantity_units", "filled_quantity_scale")
            if order is not None
            else None
        )
        if order is not None:
            accounts.add(order["account_id"])
        accounts.update(row["account_id"] for row in fills)
        checks = []
        if order is not None:
            if order["instrument_id"] != intent["symbol"]:
                checks.append("证券不一致")
            if order["side"] != intent["side"]:
                checks.append("方向不一致")
            if order_quantity != planned:
                checks.append("订单数量不一致")
            if source_filled != filled:
                checks.append("订单累计成交与成交记录不一致")
        if checks:
            mismatches.append(f"{order_id}: {'、'.join(checks)}")
        currencies = sorted({row["currency"] for row in fills})
        cost_parts = costs_by_order.get(order_id, {})
        if len(cost_parts) == 1:
            actual_cost = float(next(iter(cost_parts.values())))
            cost_currency = next(iter(cost_parts))
        elif fills and not cost_parts and len(currencies) == 1:
            actual_cost = 0.0
            cost_currency = currencies[0]
        else:
            actual_cost = None
            cost_currency = ""
        estimated_price = intent.get("estimated_execution_price")
        details.append(
            {
                "symbol": intent["symbol"],
                "account_id": order["account_id"] if order is not None else "",
                "side": intent["side"],
                "planned_quantity": float(planned),
                "order_quantity": float(order_quantity) if order_quantity is not None else None,
                "filled_quantity": float(filled),
                "fill_rate": float(filled / planned) if planned else None,
                "order_status": order["status"] if order is not None else "source_missing",
                "average_fill_price": float(average_price) if average_price is not None else None,
                "estimated_execution_price": estimated_price,
                "price_difference": (
                    float(average_price) - float(estimated_price)
                    if average_price is not None
                    and isinstance(estimated_price, (int, float))
                    and not isinstance(estimated_price, bool)
                    else None
                ),
                "actual_cost": actual_cost,
                "currency": cost_currency or (currencies[0] if len(currencies) == 1 else ""),
                "last_event_at": _iso(order["event_time"]) if order is not None else "",
                "source_filled_quantity": (
                    float(source_filled) if source_filled is not None else None
                ),
                "fill_records": len(fills),
                "evidence_check": "一致" if order is not None and not checks else "、".join(checks),
            }
        )

    position_rows: list[dict] = []
    position_run, position_manifest = contexts[-1]
    position_artifact = _artifact(position_manifest, "positions")
    position_notice = ""
    if position_artifact and 0 < position_artifact.rows <= MAX_POSITION_ROWS:
        raw_positions = _rows(
            position_run,
            position_manifest,
            "positions",
            [
                "event_time",
                "account_id",
                "instrument_id",
                "quantity_units",
                "quantity_scale",
                "market_value_units",
                "market_value_scale",
                "currency",
            ],
        )
        if raw_positions:
            latest_time = max(row["event_time"] for row in raw_positions)
            for row in raw_positions:
                if row["event_time"] != latest_time:
                    continue
                accounts.add(row["account_id"])
                position_rows.append(
                    {
                        "symbol": row["instrument_id"],
                        "account_id": row["account_id"],
                        "quantity": float(_scaled(row, "quantity_units", "quantity_scale")),
                        "market_value": float(
                            _scaled(row, "market_value_units", "market_value_scale")
                        ),
                        "currency": row["currency"],
                        "event_time": _iso(row["event_time"]),
                    }
                )
    elif position_artifact and position_artifact.rows > MAX_POSITION_ROWS:
        position_notice = f"持仓记录超过 {MAX_POSITION_ROWS} 行，未载入快照明细。"

    missing = len(proposed) - len(latest)
    notices = []
    if missing:
        notices.append(f"{missing} 条拟调仓在标准订单中没有匹配记录。")
    if mismatches:
        notices.append(f"{len(mismatches)} 条拟调仓与订单证据不一致。")
    if not fill_rows:
        notices.append("尚无模拟成交；订单状态不等同于实际成交。")
    if position_notice:
        notices.append(position_notice)
    return {
        **base,
        "available": missing == 0 and not mismatches,
        "notice": " ".join(notices),
        "matched_orders": len(latest),
        "orders_with_fills": orders_with_fills,
        "fill_records": len(fill_rows),
        "actual_costs": [
            {"currency": currency, "amount": float(amount)}
            for currency, amount in sorted(total_costs.items())
        ],
        "orders": details,
        "positions": position_rows,
        "accounts": sorted(accounts),
        "evidence_runs": [context_manifest.run_id for _, context_manifest in contexts],
    }


def account_snapshots(run: Path, manifest: RunManifestV2) -> list[dict]:
    """Return the latest exact portfolio snapshot for each account in a run."""
    artifact = _artifact(manifest, "portfolio_snapshots")
    if artifact is None or artifact.rows == 0 or artifact.rows > MAX_POSITION_ROWS:
        return []
    rows = _rows(
        run,
        manifest,
        "portfolio_snapshots",
        [
            "event_time",
            "account_id",
            "base_currency",
            "nav_units",
            "nav_scale",
            "cash_value_units",
            "cash_value_scale",
            "market_value_units",
            "market_value_scale",
        ],
    )
    latest: dict[str, dict] = {}
    for row in rows:
        existing = latest.get(row["account_id"])
        if existing is None or row["event_time"] > existing["event_time"]:
            latest[row["account_id"]] = row
    return [
        {
            "account_id": account_id,
            "event_time": _iso(row["event_time"]),
            "currency": row["base_currency"],
            "nav": float(_scaled(row, "nav_units", "nav_scale")),
            "cash": float(_scaled(row, "cash_value_units", "cash_value_scale")),
            "market_value": float(_scaled(row, "market_value_units", "market_value_scale")),
        }
        for account_id, row in sorted(latest.items())
    ]


def outcome_summary(run: Path, manifest: RunManifestV2, card: dict) -> dict:
    """Compute 1/5/20-observation outcomes only when the producer declares maturity."""
    validation = card.get("validation", {})
    observed = validation.get("forward_observation_days", 0)
    base = {
        "available": False,
        "notice": "尚未积累前向观察数据。",
        "observed_days": observed
        if isinstance(observed, int) and not isinstance(observed, bool)
        else 0,
        "windows": [{"days": days, "return": None} for days in WINDOWS],
        "observed_return": None,
        "benchmark_return": None,
    }
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
        base["notice"] = "生产者提供的前向观察天数无效。"
        return base
    if observed == 0:
        return base
    if len(manifest.strategy_ids) != 1:
        base["notice"] = "多策略运行未提供可归属到单一策略的前向收益。"
        return base
    artifact = _artifact(manifest, "returns")
    if artifact is None:
        base["notice"] = "标准运行没有收益序列。"
        return base
    if artifact.rows > MAX_RETURN_ROWS:
        base["notice"] = f"收益序列超过 {MAX_RETURN_ROWS} 行，未在静态看板中聚合。"
        return base
    rows = _rows(
        run,
        manifest,
        "returns",
        ["event_time", "strategy_id", "net_return"],
    )
    rows = [row for row in rows if row["strategy_id"] == manifest.strategy_ids[0]]
    rows.sort(key=lambda row: row["event_time"])
    if observed > len(rows):
        base["notice"] = "前向观察天数多于可验证收益记录，未计算阶段收益。"
        return base
    selected = rows[-observed:]
    unique_dates = {row["event_time"].date() for row in selected}
    if len(unique_dates) < observed:
        base["notice"] = "前向收益记录不是一日一条，未计算日窗口收益。"
        return base
    values = [row["net_return"] for row in selected]
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
        for value in values
    ):
        base["notice"] = "前向收益包含无效数值。"
        return base

    def cumulative(count: int) -> float:
        return math.prod(1.0 + value for value in values[:count]) - 1.0

    windows = [
        {"days": days, "return": cumulative(days) if observed >= days else None} for days in WINDOWS
    ]
    producer_total = validation.get("net_performance", {}).get("total_return")
    observed_return = cumulative(observed)
    notice = ""
    if (
        isinstance(producer_total, (int, float))
        and not isinstance(producer_total, bool)
        and not math.isclose(observed_return, producer_total, rel_tol=1e-8, abs_tol=1e-10)
    ):
        notice = "窗口收益与生产者累计收益口径不同；窗口值按标准净收益序列计算。"
    benchmark = validation.get("hs300_price_index", {}).get("total_return")
    return {
        **base,
        "available": True,
        "notice": notice,
        "windows": windows,
        "observed_return": observed_return,
        "benchmark_return": (
            benchmark
            if isinstance(benchmark, (int, float)) and not isinstance(benchmark, bool)
            else None
        ),
    }


def decision_change(current: dict, previous: dict | None) -> dict:
    """Compare target quantities and weights with the most recent valid decision."""
    if not current.get("card"):
        return {"available": False, "summary": "当前决策不可用。", "rows": []}
    if current["card"].get("status") != "paper_ready":
        return {
            "available": False,
            "summary": "当前状态没有可比较的目标持仓。",
            "rows": [],
        }
    if previous is None or not previous.get("card"):
        return {"available": False, "summary": "首次可比较决策。", "rows": []}

    def targets(item: dict) -> dict[str, dict]:
        return {row["symbol"]: row for row in item["card"].get("targets", [])}

    current_targets = targets(current)
    previous_targets = targets(previous)
    rows = []
    counts = {"new": 0, "exit": 0, "increase": 0, "decrease": 0, "unchanged": 0}
    for symbol in sorted(set(current_targets) | set(previous_targets)):
        old = previous_targets.get(symbol, {})
        new = current_targets.get(symbol, {})
        old_quantity = float(old.get("quantity", 0.0))
        new_quantity = float(new.get("quantity", 0.0))
        if not old and new:
            action = "new"
        elif old and not new:
            action = "exit"
        elif math.isclose(new_quantity, old_quantity, rel_tol=1e-10, abs_tol=1e-12):
            action = "unchanged"
        elif new_quantity > old_quantity:
            action = "increase"
        else:
            action = "decrease"
        counts[action] += 1
        rows.append(
            {
                "symbol": symbol,
                "change_type": action,
                "previous_quantity": old_quantity,
                "target_quantity": new_quantity,
                "quantity_change": new_quantity - old_quantity,
                "previous_weight": old.get("weight"),
                "target_weight": new.get("weight"),
                "weight_change": (
                    float(new.get("weight", 0.0)) - float(old.get("weight", 0.0))
                    if "weight" in old or "weight" in new
                    else None
                ),
            }
        )
    changed = sum(counts[key] for key in ("new", "exit", "increase", "decrease"))
    if changed == 0:
        summary = "与上次目标持仓一致。"
    else:
        labels = (("new", "新增"), ("exit", "退出"), ("increase", "增持"), ("decrease", "减持"))
        summary = " · ".join(f"{label} {counts[key]}" for key, label in labels if counts[key])
    current_identity = current.get("identity", {})
    previous_identity = previous.get("identity", {})
    return {
        "available": True,
        "previous_run_id": previous["run_id"],
        "summary": summary,
        "changed": changed,
        "counts": counts,
        "config_changed": bool(
            current_identity.get("config_sha256")
            and previous_identity.get("config_sha256")
            and current_identity["config_sha256"] != previous_identity["config_sha256"]
        ),
        "code_changed": bool(
            current_identity.get("code_version")
            and previous_identity.get("code_version")
            and current_identity["code_version"] != previous_identity["code_version"]
        ),
        "rows": rows,
    }
