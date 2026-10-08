"""Chronological cost diagnostics on a natively reconstructed cash account."""

from __future__ import annotations

import html
import io
import json
import tempfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

import pandas as pd

from quant_report_hub.cash_attribution import _check
from quant_report_hub.cash_price_bridge import _build as build_bridge
from quant_report_hub.cash_price_bridge import _json_bytes
from quant_report_hub.execution_references import _fields, _object, digest, fingerprint

SCHEMA = "quant-report-hub.execution-cost-diagnostics/v1"
POLICY = "quant-report-hub.execution-cost-policy/v1"
LIMITATIONS = [
    "成交偏差相对订单接受时可得报价中点，包含等待期间行情变化，不是纯市场冲击。",
    "只用训练期成交按参考名义金额加权估计有符号价差基点；留出期不参与拟合，不修改账户。",
    "同一订单的部分成交合并为一个观察组；观察组并不保证统计独立。跨训练截止的订单整体排除。",
    "时间划分由调用者指定，哈希不证明划分曾事前登记；这是历史诊断，不是新增自然前向。",
    "合成和模型报价只用于软件与假设验证；提供者声明的独立报价仍需外部核验。",
    "仅支持原生现金证券归因的同币种多头账户，原生费用单列；不拟合借券、税收、FX或保证金成本。",
]


def _time(value):
    _check(isinstance(value, str), "策略时点必须为带时区字符串")
    result = pd.Timestamp(value)
    _check(not pd.isna(result) and result.tzinfo is not None, "策略时点必须带时区")
    return result.tz_convert("UTC")


def _read_policy(path, expected):
    path = Path(path).absolute()
    identity = fingerprint([path])
    raw = path.read_bytes()
    _check(digest(raw) == expected == identity[path][0], "成本策略SHA-256不一致")
    policy = json.loads(raw, object_pairs_hook=_object)
    _fields(
        policy,
        (
            "schema_version",
            "training_end",
            "holdout_start",
            "minimum_train_orders",
            "minimum_holdout_orders",
            "adverse_budget_bps",
        ),
        "成本策略",
    )
    _check(policy["schema_version"] == POLICY, "成本策略schema不受支持")
    parsed = dict(policy)
    for key in ("training_end", "holdout_start"):
        parsed[key] = _time(policy[key])
    _check(parsed["training_end"] < parsed["holdout_start"], "留出期必须晚于训练截止")
    for key in ("minimum_train_orders", "minimum_holdout_orders"):
        _check(
            type(policy[key]) is int and 1 <= policy[key] <= 1_000_000, "最小订单组数必须为正整数"
        )
    try:
        _check(isinstance(policy["adverse_budget_bps"], str), "成本预算必须为十进制字符串")
        budget = Decimal(policy["adverse_budget_bps"])
        _check(budget.is_finite() and 0 <= budget <= 10000, "成本预算必须在0至10000基点之间")
    except InvalidOperation as exc:
        raise ValueError("成本预算不是有效十进制数") from exc
    parsed["adverse_budget_bps"] = budget
    return policy, parsed, identity


def summarize_orders(fills, policy):
    """Count order groups, retaining partial fills and signed improvements."""
    groups = defaultdict(list)
    for row in fills:
        groups[row["order_id"]].append(row)
    orders = []
    for order_id, rows in sorted(groups.items()):
        accepted = {pd.Timestamp(row["accepted_at"]) for row in rows}
        _check(len(accepted) == 1, "订单接受时点不一致")
        start = accepted.pop()
        end = max(pd.Timestamp(row["event_time"]) for row in rows)
        for field in ("instrument_id", "side", "currency"):
            _check(len({row[field] for row in rows}) == 1, f"订单{field}不一致")
        if start <= policy["training_end"]:
            partition = (
                "training" if end <= policy["training_end"] else "excluded_crosses_training_end"
            )
        elif start >= policy["holdout_start"]:
            partition = "holdout"
        else:
            partition = "excluded_gap"
        notional = sum(
            (Decimal(str(r["quantity"])) * Decimal(str(r["reference_price"])) for r in rows),
            Decimal(0),
        )
        cost = sum((Decimal(str(r["raw_adverse_cost"])) for r in rows), Decimal(0))
        _check(notional > 0 and notional.is_finite() and cost.is_finite(), "成交组名义金额无效")
        bps = cost / notional * 10000
        orders.append(
            {
                "order_id": order_id,
                "instrument_id": rows[0]["instrument_id"],
                "side": rows[0]["side"],
                "currency": rows[0]["currency"],
                "accepted_at": start.isoformat(),
                "last_fill_at": end.isoformat(),
                "fills": len(rows),
                "partition": partition,
                "reference_notional": str(notional),
                "signed_adverse_cost": str(cost),
                "signed_adverse_bps": str(bps),
            }
        )
    train = [row for row in orders if row["partition"] == "training"]
    holdout = [row for row in orders if row["partition"] == "holdout"]
    reasons = []
    if len(train) < policy["minimum_train_orders"]:
        reasons.append("insufficient_training_orders")
    if len(holdout) < policy["minimum_holdout_orders"]:
        reasons.append("insufficient_holdout_orders")

    def rate(rows):
        return (
            sum((Decimal(r["signed_adverse_cost"]) for r in rows), Decimal(0))
            / sum((Decimal(r["reference_notional"]) for r in rows), Decimal(0))
            * 10000
        )

    fit = None if len(train) < policy["minimum_train_orders"] else rate(train)
    measured = None if not holdout else rate(holdout)
    error = None if reasons else measured - fit
    for row in orders:
        notional = Decimal(row["reference_notional"])
        predicted = (
            fit * notional / 10000 if fit is not None and row["partition"] == "holdout" else None
        )
        row["predicted_signed_cost"] = str(predicted) if predicted is not None else ""
        row["prediction_residual"] = (
            str(Decimal(row["signed_adverse_cost"]) - predicted) if predicted is not None else ""
        )
        row["budget_breach"] = str(
            Decimal(row["signed_adverse_bps"]) > policy["adverse_budget_bps"]
        ).lower()
    summary = {
        "status": "no_trades"
        if not orders
        else ("insufficient_samples" if reasons else "computed"),
        "reasons": reasons,
        "training_orders": len(train),
        "holdout_orders": len(holdout),
        "excluded_orders": len(orders) - len(train) - len(holdout),
        "fitted_adverse_bps": str(fit) if fit is not None else None,
        "holdout_adverse_bps": str(measured) if measured is not None else None,
        "holdout_prediction_error_bps": str(error) if error is not None else None,
        "holdout_budget_breaches": sum(
            Decimal(r["signed_adverse_bps"]) > policy["adverse_budget_bps"] for r in holdout
        ),
        "adverse_budget_bps": str(policy["adverse_budget_bps"]),
    }
    return orders, summary


def _render(receipt, orders):
    summary = receipt["summary"]
    escape = lambda value: html.escape(str(value))
    shown = lambda value: "不可用" if value is None else format(Decimal(str(value)), ".4f")
    status = {
        "computed": "已计算",
        "insufficient_samples": "样本不足",
        "no_trades": "无成交",
    }[summary["status"]]
    kind = {
        "synthetic": "合成报价·软件验证",
        "model": "模型报价·假设诊断",
        "independently_observed": "独立观察报价·提供者声明",
    }[receipt["references"]["source"]["evidence_kind"]]
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>成交成本诊断</title><style>body{font:16px system-ui;background:#f4f6fa;color:#172d45;margin:0}main{max-width:1100px;margin:auto;padding:24px}section{background:white;padding:20px;border:1px solid #d6dfea;border-radius:12px;margin:16px 0}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #d6dfea;white-space:nowrap;text-align:right}th:first-child,td:first-child{text-align:left}p{overflow-wrap:anywhere}li{margin:8px 0}@media(max-width:600px){main{padding:12px}section{padding:12px}}</style><main><h1>成交成本诊断</h1>'
    page += f"<section><p>{kind}；币种：{escape(receipt['currency'])}；状态：{status}。</p><p>正基点为不利成本，负基点为成交改善。真实执行校准：未认证。</p>"
    for label, key in (
        ("训练订单组", "training_orders"),
        ("留出订单组", "holdout_orders"),
        ("排除订单组", "excluded_orders"),
        ("训练估计/基点", "fitted_adverse_bps"),
        ("留出实测/基点", "holdout_adverse_bps"),
        ("留出预测偏差/基点", "holdout_prediction_error_bps"),
        ("留出预算超限组数", "holdout_budget_breaches"),
    ):
        value = shown(summary[key]) if key.endswith("bps") else summary[key]
        page += f"<p>{label}：{escape(value)}</p>"
    page += f"<p>原账本净损益：{escape(receipt['native_net_pnl'])}；原账本费用现金影响：{escape(receipt['native_fee_cash'])}。费用不与价差重复相加，不改写原净值。</p></section>"
    policy = receipt["policy"]
    page += "<section><h2>观察窗口与解释范围</h2>"
    for label, key in (
        ("训练截止", "training_end"),
        ("留出起点", "holdout_start"),
        ("最少训练订单组", "minimum_train_orders"),
        ("最少留出订单组", "minimum_holdout_orders"),
        ("不利成本预算/基点", "adverse_budget_bps"),
    ):
        page += f"<p>{label}：{escape(policy[key])}</p>"
    page += "<ul>"
    page += "".join(f"<li>{escape(item)}</li>" for item in LIMITATIONS) + "</ul></section>"
    preview = pd.DataFrame(orders).head(100)
    if not preview.empty:
        preview = preview[
            [
                "order_id",
                "instrument_id",
                "side",
                "partition",
                "fills",
                "reference_notional",
                "signed_adverse_cost",
                "signed_adverse_bps",
                "prediction_residual",
            ]
        ].copy()
        for column in (
            "reference_notional",
            "signed_adverse_cost",
            "signed_adverse_bps",
            "prediction_residual",
        ):
            preview[column] = preview[column].map(
                lambda value: shown(value) if value != "" else "不可用"
            )
        preview = preview.rename(
            columns=dict(
                zip(
                    preview.columns,
                    (
                        "订单",
                        "证券",
                        "方向",
                        "区间",
                        "成交笔数",
                        "参考名义金额",
                        "有符号成本",
                        "不利基点",
                        "预测金额偏差",
                    ),
                )
            )
        )
    table = preview.to_html(index=False, escape=True, border=0)
    page += (
        '<section><h2>逐订单组</h2><p>预览前100组，数值显示四位小数；完整精度和字段见CSV。</p><div class="scroll" tabindex="0">'
        + table
        + '</div></section><p><a href="orders.csv">完整订单组CSV</a> · <a href="summary.json">汇总</a> · <a href="manifest.json">证据清单</a></p></main></html>'
    )
    return page.encode("utf-8")


def _build(run_dir, references, references_sha256, policy, policy_sha256):
    original, parsed, identity = _read_policy(policy, policy_sha256)
    bridge, content, native_unchanged = build_bridge(run_dir, references, references_sha256)
    fills = pd.read_csv(
        io.BytesIO(content["fill_price_bridge.csv"]), dtype=str, keep_default_na=False
    )
    with localcontext() as context:
        context.prec = 28
        orders, summary = summarize_orders(fills.to_dict("records"), parsed)
    receipt = {
        "schema_version": SCHEMA,
        "source_run_manifest_sha256": bridge["source_run_manifest_sha256"],
        "source_run_id": bridge["source_run_id"],
        "source_code_version": bridge["source_code_version"],
        "references_sha256": references_sha256,
        "references": bridge["references"],
        "policy_sha256": policy_sha256,
        "policy": original,
        "summary": summary,
        "currency": bridge["summary"]["currency"],
        "native_net_pnl": bridge["summary"]["net_pnl"],
        "native_fee_cash": bridge["summary"]["fee_cash"],
        "real_execution_calibrated": False,
        "new_forward_evidence": False,
        "limitations": LIMITATIONS,
    }
    columns = [
        "order_id",
        "instrument_id",
        "side",
        "currency",
        "accepted_at",
        "last_fill_at",
        "fills",
        "partition",
        "reference_notional",
        "signed_adverse_cost",
        "signed_adverse_bps",
        "predicted_signed_cost",
        "prediction_residual",
        "budget_breach",
    ]
    files = {
        "orders.csv": pd.DataFrame(orders, columns=columns)
        .to_csv(index=False, lineterminator="\n")
        .encode("utf-8"),
        "summary.json": _json_bytes(summary),
        "report.html": _render(receipt, orders),
    }
    receipt["files"] = {name: digest(raw) for name, raw in files.items()}
    files["manifest.json"] = _json_bytes(receipt)

    def unchanged():
        native_unchanged()
        _check(fingerprint(identity) == identity, "成本策略在诊断期间变化")

    unchanged()
    return receipt, files, unchanged


def write_execution_diagnostics(
    run_dir, *, references, references_sha256, policy, policy_sha256, out_dir
):
    destination = Path(out_dir).resolve()
    for root in (
        Path(run_dir).resolve(),
        Path(references).resolve().parent,
        Path(policy).resolve(),
    ):
        _check(destination != root and root not in destination.parents, "诊断必须位于来源之外")
    _check(not destination.exists(), "报告目录已存在，拒绝覆盖")
    receipt, files, unchanged = _build(
        run_dir, references, references_sha256, policy, policy_sha256
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".cost-diagnostics-", dir=destination.parent
    ) as temporary:
        staged = Path(temporary) / "report"
        staged.mkdir()
        for name, raw in files.items():
            (staged / name).write_bytes(raw)
        unchanged()
        _check(not destination.exists(), "报告目录已存在，拒绝覆盖")
        staged.rename(destination)
    return receipt


def verify_execution_diagnostics(
    run_dir, *, references, references_sha256, policy, policy_sha256, report_dir, manifest_sha256
):
    root = Path(report_dir)
    _check(not root.is_symlink(), "报告不能是符号链接")
    _check(digest((root / "manifest.json").read_bytes()) == manifest_sha256, "报告摘要不符")
    receipt, files, unchanged = _build(
        run_dir, references, references_sha256, policy, policy_sha256
    )
    _check({p.name for p in root.iterdir()} == set(files), "报告文件集合不一致")
    for name, raw in files.items():
        path = root / name
        _check(
            path.is_file() and not path.is_symlink() and path.read_bytes() == raw,
            f"诊断与原生重算不一致: {name}",
        )
    unchanged()
    return receipt
