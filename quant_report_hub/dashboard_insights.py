"""Derived risk, alert, and account views for validated dashboard inputs."""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any


def _finite(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def risk_summary(card: dict) -> dict:
    """Summarize producer limits without inventing unavailable exposures."""
    if not card:
        return {"available": False, "metrics": [], "breaches": []}
    risk = card.get("risk", {})
    allocation = risk.get("allocation", {}) if isinstance(risk.get("allocation"), dict) else {}
    targets = card.get("targets", [])
    weighted = [
        (row.get("symbol", ""), value)
        for row in targets
        if (value := _finite(row.get("weight"))) is not None
    ]
    checks = risk.get("portfolio_checks", [])
    latest_check = checks[-1] if isinstance(checks, list) and checks else {}
    check_metrics = latest_check.get("metrics", {}) if isinstance(latest_check, dict) else {}
    gross_weight = (
        sum(value for _, value in weighted)
        if weighted
        else _finite(check_metrics.get("gross_weight"))
    )
    largest = max(weighted, key=lambda row: row[1]) if weighted else ("", None)
    limits = [
        value
        for value in (
            _finite(risk.get("max_single_weight")),
            _finite(allocation.get("max_position_weight")),
        )
        if value is not None
    ]
    max_weight_limit = min(limits) if limits else None
    drawdown = _finite(card.get("validation", {}).get("net_performance", {}).get("max_drawdown"))
    drawdown = abs(drawdown) if drawdown is not None else None
    drawdown_limit = _finite(risk.get("max_drawdown"))
    nav = _finite(risk.get("nav"))
    cost = _finite(card.get("estimated_cost", {}).get("total"))
    cost_bps = cost / nav * 10_000 if cost is not None and nav and nav > 0 else None
    cash_buffer = _finite(allocation.get("cash_buffer"))
    projected_cash = _finite(check_metrics.get("cash_weight"))
    if projected_cash is None and gross_weight is not None:
        projected_cash = 1.0 - gross_weight
    turnover = _finite(check_metrics.get("turnover"))
    position_count = _finite(check_metrics.get("positions"))
    industry_weights = check_metrics.get("industry_weights", {})
    industry_values = (
        [value for value in industry_weights.values()] if isinstance(industry_weights, dict) else []
    )
    finite_industry_values = [
        parsed for value in industry_values if (parsed := _finite(value)) is not None
    ]
    largest_industry = max(finite_industry_values, default=None)

    breaches = []
    if largest[1] is not None and max_weight_limit is not None and largest[1] > max_weight_limit:
        breaches.append(
            {
                "code": "target_concentration",
                "severity": "critical",
                "message": (
                    f"{largest[0]} 目标权重 {largest[1]:.2%} 超过生效上限 {max_weight_limit:.2%}。"
                ),
            }
        )
    if drawdown is not None and drawdown_limit is not None and drawdown > drawdown_limit:
        breaches.append(
            {
                "code": "drawdown_limit",
                "severity": "critical",
                "message": f"已观察最大回撤 {drawdown:.2%} 超过上限 {drawdown_limit:.2%}。",
            }
        )
    if projected_cash is not None and projected_cash < -1e-9:
        breaches.append(
            {
                "code": "target_leverage",
                "severity": "critical",
                "message": f"目标权重合计 {gross_weight:.2%}，超过 100%。",
            }
        )
    elif (
        projected_cash is not None
        and cash_buffer is not None
        and projected_cash + 1e-9 < cash_buffer
    ):
        breaches.append(
            {
                "code": "cash_buffer",
                "severity": "warning",
                "message": (f"目标现金比例 {projected_cash:.2%} 低于配置缓冲 {cash_buffer:.2%}。"),
            }
        )
    existing_codes = {item["code"] for item in breaches}
    for alert in latest_check.get("alerts", []) if isinstance(latest_check, dict) else []:
        code = str(alert.get("rule_id", "portfolio.risk"))
        if alert.get("severity") not in {"critical", "warning"} or code in existing_codes:
            continue
        breaches.append(
            {
                "code": code,
                "severity": alert["severity"],
                "message": str(alert.get("message", "组合风险检查未通过。")),
            }
        )
        existing_codes.add(code)
    return {
        "available": bool(weighted or check_metrics or nav is not None or drawdown is not None),
        "metrics": [
            {
                "label": "模拟净值",
                "value": nav,
                "kind": "number",
                "currency": risk.get("currency", ""),
            },
            {"label": "目标总权重", "value": gross_weight, "kind": "percent", "currency": ""},
            {
                "label": "最大目标权重",
                "value": largest[1],
                "kind": "percent",
                "currency": largest[0],
            },
            {"label": "生效单仓上限", "value": max_weight_limit, "kind": "percent", "currency": ""},
            {"label": "目标现金比例", "value": projected_cash, "kind": "percent", "currency": ""},
            {"label": "配置现金缓冲", "value": cash_buffer, "kind": "percent", "currency": ""},
            {"label": "预计换手", "value": turnover, "kind": "percent", "currency": ""},
            {"label": "目标持仓数", "value": position_count, "kind": "number", "currency": ""},
            {
                "label": "最大行业权重",
                "value": largest_industry,
                "kind": "percent",
                "currency": "",
            },
            {"label": "已观察最大回撤", "value": drawdown, "kind": "percent", "currency": ""},
            {"label": "回撤上限", "value": drawdown_limit, "kind": "percent", "currency": ""},
            {"label": "预计成本／净值", "value": cost_bps, "kind": "bps", "currency": ""},
        ],
        "breaches": breaches,
    }


def build_alerts(sources: list[dict], experiments: list[dict]) -> list[dict]:
    """Build a stable machine-readable alert feed from the current snapshot."""
    alerts: list[dict] = []

    def add(source: dict, code: str, severity: str, message: str, evidence: str = "") -> None:
        item = source["current"]
        identity = item.get("identity", {})
        alerts.append(
            {
                "alert_id": f"{source['source_id']}:{item['run_id']}:{code}",
                "severity": severity,
                "code": code,
                "source": Path(source["root"]).name,
                "source_id": source["source_id"],
                "project": identity.get("project", ""),
                "run_id": item["run_id"],
                "message": message,
                "evidence": evidence or item.get("path", ""),
            }
        )

    for source in sources:
        item = source["current"]
        status = item["status"]
        if status == "invalid":
            add(source, "source_invalid", "critical", item.get("error") or "最新来源无法校验。")
            continue
        if status == "blocked":
            reasons = "；".join(item.get("card", {}).get("reasons", [])) or "生产运行被阻断。"
            add(source, "run_blocked", "critical", reasons)
        elif status == "expired":
            add(source, "decision_expired", "warning", "最新决策已经超过有效期，需要刷新生产运行。")
        execution = item.get("execution", {})
        if execution.get("planned_orders", 0) and not execution.get("available"):
            add(
                source,
                "execution_evidence",
                "critical",
                execution.get("notice") or "计划订单与标准执行证据不一致。",
            )
        elif execution.get("planned_orders", 0) and not execution.get("fill_records"):
            add(source, "fills_pending", "info", "拟调仓已进入模拟账本，尚无下一交易日成交。")
        for breach in item.get("risk_summary", {}).get("breaches", []):
            add(source, breach["code"], breach["severity"], breach["message"])
        outcome = item.get("outcome", {})
        if item.get("card") and outcome and outcome.get("observed_days", 0) < 20:
            add(
                source,
                "forward_window_immature",
                "info",
                f"前向证据已成熟 {outcome.get('observed_days', 0)} 个交易日，20 日窗口尚未完成。",
            )

    for index, row in enumerate(experiments):
        if not row.get("error"):
            continue
        alerts.append(
            {
                "alert_id": f"experiment:{index}:{row.get('run_id', '')}:invalid",
                "severity": "warning",
                "code": "experiment_invalid",
                "source": "experiment-index",
                "source_id": "",
                "project": row.get("project", ""),
                "run_id": row.get("run_id", ""),
                "message": row["error"],
                "evidence": row.get("run_path", ""),
            }
        )
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda row: (order.get(row["severity"], 9), row["alert_id"]))


def account_summary(sources: list[dict], alerts: list[dict]) -> list[dict]:
    """Aggregate current validated account snapshots across decision roots."""
    alert_counts = Counter(row["source_id"] for row in alerts if row["severity"] != "info")
    rows = []
    for source in sources:
        item = source["current"]
        identity = item.get("identity", {})
        execution = item.get("execution", {})
        orders = execution.get("orders", [])
        snapshots = item.get("account_snapshots", [])
        account_ids = {row["account_id"] for row in snapshots}
        account_ids.update(execution.get("accounts", []))
        for account_id in sorted(account_ids):
            snapshot = next((row for row in snapshots if row["account_id"] == account_id), {})
            account_orders = [row for row in orders if row.get("account_id") == account_id]
            rows.append(
                {
                    "source": Path(source["root"]).name,
                    "project": identity.get("project", ""),
                    "strategies": "、".join(identity.get("strategies", [])),
                    "account_id": account_id,
                    "status": item["status"],
                    "nav": snapshot.get("nav"),
                    "cash": snapshot.get("cash"),
                    "market_value": snapshot.get("market_value"),
                    "currency": snapshot.get("currency", identity.get("base_currency", "")),
                    "planned_orders": len(account_orders),
                    "filled_orders": sum(bool(row.get("fill_records")) for row in account_orders),
                    "alerts": alert_counts[source["source_id"]],
                    "as_of": item.get("card", {}).get("as_of", ""),
                }
            )
    return rows
