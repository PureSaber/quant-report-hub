"""Signed execution-price bridge on the existing native cash reconciliation.

This leaves holdings, marks, fees and the journal untouched. The reference-value
remainder is an algebraic bridge, not a re-simulated feasible account or impact
estimate. The legacy M5 booked-slippage contract is deliberately independent.
"""

from __future__ import annotations

import html
import json
import tempfile
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

import pandas as pd

from quant_report_hub.attribution import _read_validated_v2
from quant_report_hub.cash_attribution import ZERO, _check, _fixed, _reconstruct, _records, _unique
from quant_report_hub.execution_references import digest, fingerprint, load_references, select_quote

SCHEMA = "quant-report-hub.cash-price-bridge/v1"
FILL_COLUMNS = (
    "event_time",
    "period_end",
    "account_id",
    "strategy_id",
    "instrument_id",
    "order_id",
    "fill_id",
    "side",
    "accepted_at",
    "quote_id",
    "quote_observed_at",
    "quote_available_at",
    "bid",
    "ask",
    "reference_price",
    "fill_price",
    "quantity",
    "currency",
    "cash_scale",
    "native_trade_cash",
    "reference_trade_cash",
    "raw_adverse_cost",
    "execution_price_pnl",
    "rounding_pnl",
    "residual",
)
LIMITATIONS = [
    "保留原持仓、估值、公司行动与费用；参考价剩余项是代数分解，不是重新回测或可成交的替代账户。",
    "成交价差损益正值为有利改善、负值为不利成本；包含订单接受至成交的价格变化，不单独识别市场冲击。",
    "报价按订单首次接受时已可得的最新中点选取；部分成交共用同一订单参考时点；跨公司行动的报价拒绝使用。",
    "报价来源及可得时间由提供者声明；哈希核验不独立证明其真实性。合成或模型报价仅验证软件和假设。",
    "只覆盖单账户、单策略、同币种、单位乘数的多头现金证券；完整现金机会成本、FX和保证金不在本报告范围。",
]


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _fills(frames, quotes, policy, summary, period_ends):
    orders = _unique(_records(frames["orders"]), "order_id")
    accepts = defaultdict(list)
    for event in _records(frames["order_events"]):
        if event["from_status"] == "created" and event["to_status"] == "accepted":
            accepts[event["order_id"]].append(event["event_time"])
    ledger = _records(frames["cash_ledger"])
    cash = {
        row["reference_id"]: row
        for row in ledger
        if row["event_type"] == "fill" and row["ledger_account"] == "assets:cash"
    }
    actions = [row for row in ledger if row["event_type"] == "corporate_action"]
    rows = []
    for fill in sorted(_records(frames["fills"]), key=lambda f: (f["event_time"], f["fill_id"])):
        order_id = fill["order_id"]
        _check(
            order_id in orders and len(accepts[order_id]) == 1, "成交必须对应唯一原生订单接受事件"
        )
        order = orders[order_id]
        for field in ("account_id", "strategy_id", "instrument_id", "side"):
            _check(fill[field] == order[field], f"成交与订单{field}不一致")
        _check(
            fill["account_id"] == summary["account_id"]
            and fill["strategy_id"] == summary["strategy_id"],
            "成交账户或策略不一致",
        )
        accepted = accepts[order_id][0]
        _check(accepted <= fill["event_time"], "成交早于订单接受")
        quote = select_quote(
            quotes, fill["instrument_id"], fill["currency"], accepted, policy["max_quote_age_ms"]
        )
        _check(
            not any(
                row["instrument_id"] == fill["instrument_id"]
                and quote["observed_at"] <= row["event_time"] <= fill["event_time"]
                for row in actions
            ),
            "报价与成交跨公司行动，缺少同单位参考价",
        )
        cash_row = cash[fill["fill_id"]]
        native = _fixed(cash_row, "amount")
        quantity, price = _fixed(fill, "quantity"), _fixed(fill, "price")
        sign = Decimal(1 if fill["side"] == "buy" else -1)
        scale = int(cash_row["amount_scale"])
        reference_cash = (-sign * quantity * quote["midpoint"]).quantize(
            Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN
        )
        raw_cost = sign * quantity * (price - quote["midpoint"])
        effect = native - reference_cash
        period = next((end for end in period_ends if end >= fill["event_time"]), None)
        _check(period is not None, "来源收益边界未覆盖成交")
        rows.append(
            {
                **{
                    key: fill[key]
                    for key in (
                        "event_time",
                        "account_id",
                        "strategy_id",
                        "instrument_id",
                        "order_id",
                        "fill_id",
                        "side",
                        "currency",
                    )
                },
                "period_end": period,
                "accepted_at": accepted,
                "quote_id": quote["quote_id"],
                "quote_observed_at": quote["observed_at"],
                "quote_available_at": quote["available_at"],
                "bid": quote["bid"],
                "ask": quote["ask"],
                "reference_price": quote["midpoint"],
                "fill_price": price,
                "quantity": quantity,
                "cash_scale": scale,
                "native_trade_cash": native,
                "reference_trade_cash": reference_cash,
                "raw_adverse_cost": raw_cost,
                "execution_price_pnl": effect,
                "rounding_pnl": effect + raw_cost,
                "residual": native - reference_cash - effect,
            }
        )
    return pd.DataFrame(rows, columns=FILL_COLUMNS)


def _bridge(tables, fills):
    instrument_keys = {
        (row["event_time"], row["instrument_id"])
        for row in tables["instrument_pnl.csv"].to_dict("records")
    }
    _check(
        all(
            (row["period_end"], row["instrument_id"]) in instrument_keys
            for row in fills.to_dict("records")
        ),
        "成交缺少原生证券期间归属",
    )
    effects, raw_costs, rounding = (defaultdict(lambda: ZERO) for _ in range(3))
    for row in fills.to_dict("records"):
        for key in (row["period_end"], (row["period_end"], row["instrument_id"])):
            effects[key] += row["execution_price_pnl"]
            raw_costs[key] += row["raw_adverse_cost"]
            rounding[key] += row["rounding_pnl"]
    output = {}
    for source, target in (
        ("period_reconciliation.csv", "period_price_bridge.csv"),
        ("instrument_pnl.csv", "instrument_price_bridge.csv"),
    ):
        rows = []
        for row in tables[source].to_dict("records"):
            key = (
                (row["event_time"], row["instrument_id"])
                if "instrument_id" in row
                else row["event_time"]
            )
            remainder = row["valuation_and_trading_pnl"] - effects[key]
            residual = row["net_pnl"] - (
                remainder + effects[key] + row["corporate_income"] + row["fee_cash"]
            )
            _check(residual == 0, "参考价分解不守恒")
            rows.append(
                {
                    **row,
                    "reference_price_valuation_pnl": remainder,
                    "execution_price_pnl": effects[key],
                    "raw_adverse_cost": raw_costs[key],
                    "rounding_pnl": rounding[key],
                    "bridge_residual": residual,
                }
            )
        output[target] = pd.DataFrame(
            rows,
            columns=[
                *tables[source].columns,
                "reference_price_valuation_pnl",
                "execution_price_pnl",
                "raw_adverse_cost",
                "rounding_pnl",
                "bridge_residual",
            ],
        )
    for target in output.values():
        _check(
            sum(target.execution_price_pnl, ZERO) == sum(fills.execution_price_pnl, ZERO),
            "成交价差未完全分配到期间及证券",
        )
    return output


def _render(summary, provenance, tables):
    def escape(value):
        return html.escape(str(value))

    names = {
        "synthetic": "合成报价·软件验证",
        "model": "模型报价·假设分析",
        "independently_observed": "独立观察报价·提供者声明",
    }
    cards = [
        ("原账本净损益", summary["net_pnl"]),
        ("成交价差损益", summary["execution_price_pnl"]),
        ("有利成交改善", summary["favorable_pnl"]),
        ("不利成交损失", summary["adverse_pnl"]),
    ]
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>成交参考价与账本归因</title><style>body{font:16px system-ui;margin:0;background:#f3f6fb;color:#182537}main{max-width:1200px;margin:auto;padding:24px;min-width:0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card,section{background:white;border:1px solid #dbe3ee;border-radius:12px;padding:18px;margin-bottom:18px}.card strong{display:block;font-size:24px;overflow-wrap:anywhere}.muted{color:#58677c}.badge{background:#fff0cb;padding:10px;border-radius:8px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border-bottom:1px solid #dbe3ee;white-space:nowrap;text-align:right}td:first-child,th:first-child{text-align:left}a{color:#1d54ae}li{margin:8px 0}summary{cursor:pointer;font-weight:600}h1{font-size:28px}@media(max-width:600px){main{padding:12px}.cards{grid-template-columns:1fr 1fr}.card{padding:12px}.card strong{font-size:20px}}</style><main><h1>成交参考价与账本归因</h1>'
    page += f'<p class="badge">{names[provenance["source"]["evidence_kind"]]}；币种：{escape(summary["currency"])}。全成交覆盖、原生账本及分解对账通过。</p><div class="cards">'
    page += (
        "".join(
            f'<div class="card"><span class="muted">{name}</span><strong>{escape(value)}</strong></div>'
            for name, value in cards
        )
        + "</div>"
    )
    if summary["fills_checked"] == 0:
        page += '<p class="badge">原生运行无成交；仅核验现金账本，不产生执行质量结论。</p>'
    page += f"<section><h2>参考价口径</h2><p>来源：{escape(provenance['source']['provider'])}；数据集：{escape(provenance['source']['dataset_id'])}。</p><p>{escape(provenance['source']['description'])}</p><p>订单首次接受时已可得的最新未复权买卖报价中点；最大报价年龄{provenance['policy']['max_quote_age_ms']}毫秒。覆盖{summary['fills_checked']}笔成交。</p><p>净损益=参考价估值剩余项+成交价差损益+公司行动收益+原生费用现金影响。</p><p>成交价差损益=原生成交现金−参考价名义现金；正值为改善，负值为成本。参考现金沿用每笔原生现金精度和ROUND_HALF_EVEN；舍入影响单列。</p><details><summary>解释边界与证据性质</summary><ul>"
    page += (
        "".join(f"<li>{escape(item)}</li>" for item in LIMITATIONS) + "</ul></details></section>"
    )
    periods = tables["period_price_bridge.csv"][
        [
            "event_time",
            "reference_price_valuation_pnl",
            "execution_price_pnl",
            "corporate_income",
            "fee_cash",
            "net_pnl",
            "bridge_residual",
        ]
    ].copy()
    periods.columns = [
        "期间结束",
        "参考价估值剩余",
        "成交价差损益",
        "公司行动收益",
        "费用现金影响",
        "净损益",
        "残差",
    ]
    fills = tables["fill_price_bridge.csv"][
        [
            "fill_id",
            "side",
            "quote_id",
            "reference_price",
            "fill_price",
            "quantity",
            "execution_price_pnl",
            "rounding_pnl",
            "residual",
        ]
    ].copy()
    fills.columns = [
        "成交",
        "方向",
        "报价",
        "参考中点",
        "成交价格",
        "数量",
        "价差损益",
        "舍入影响",
        "残差",
    ]
    for title, frame in (("逐期间损益对账", periods), ("逐成交参考价", fills)):
        page += f'<section><h2>{title}</h2><p class="muted">预览前100行；完整明细可下载。</p><div class="scroll">{frame.head(100).to_html(index=False, border=0, escape=True)}</div></section>'
    page += (
        "<section><h2>完整数据与证据</h2><p>"
        + " · ".join(f'<a href="{name}">{name}</a>' for name in tables)
        + '</p><p><a href="manifest.json">报告清单</a></p></section></main></html>'
    )
    return page.encode("utf-8")


def _build(run_dir, references, references_sha256):
    source = Path(run_dir).resolve()
    reference_path = Path(references).absolute()
    base = source / "standard" / "v2"
    run_identity = fingerprint(base.iterdir())
    _, manifest, frames, run_hash = _read_validated_v2(source)
    _check(run_hash == run_identity[base / "run_manifest.json"][0], "读取期间原生清单变化")
    with localcontext() as context:
        context.prec = 80
        provenance, quotes, quote_identity = load_references(
            reference_path, references_sha256, run_hash
        )
        tables, summary = _reconstruct(manifest, frames)
        ends = list(tables["period_reconciliation.csv"].event_time)
        fills = _fills(frames, quotes, provenance["policy"], summary, ends)
        tables.update(_bridge(tables, fills))
        tables["fill_price_bridge.csv"] = fills
        effect = sum(fills.execution_price_pnl, ZERO)
        summary.update(
            {
                "execution_price_pnl": str(effect),
                "reference_price_valuation_pnl": str(
                    Decimal(summary["valuation_and_trading_pnl"]) - effect
                ),
                "raw_adverse_cost": str(sum(fills.raw_adverse_cost, ZERO)),
                "rounding_pnl": str(sum(fills.rounding_pnl, ZERO)),
                "favorable_pnl": str(sum((v for v in fills.execution_price_pnl if v > 0), ZERO)),
                "adverse_pnl": str(sum((v for v in fills.execution_price_pnl if v < 0), ZERO)),
                "fills_checked": len(fills),
                "bridge_residual": "0",
            }
        )
    content = {
        name: frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        for name, frame in tables.items()
    }
    content["report.html"] = _render(summary, provenance, tables)
    receipt = {
        "schema_version": SCHEMA,
        "source_run_manifest_sha256": run_hash,
        "source_run_id": manifest.run_id,
        "source_project": manifest.project,
        "source_code_version": manifest.code_version,
        "references_sha256": references_sha256,
        "references": provenance,
        "summary": summary,
        "limitations": LIMITATIONS,
        "row_counts": {name: len(frame) for name, frame in tables.items()},
        "files": {name: digest(value) for name, value in content.items()},
    }
    content["manifest.json"] = _json_bytes(receipt)

    def unchanged():
        _check(fingerprint(base.iterdir()) == run_identity, "原生来源在归因期间变化")
        _check(fingerprint(quote_identity) == quote_identity, "参考价来源在归因期间变化")

    unchanged()
    return receipt, content, unchanged


def write_cash_price_bridge(run_dir, *, references, references_sha256, out_dir):
    """Publish only after complete source, quote and accounting verification."""
    destination = Path(out_dir).resolve()
    for root in (Path(run_dir).resolve(), Path(references).resolve().parent):
        _check(destination != root and root not in destination.parents, "报告必须位于来源目录之外")
    _check(not destination.exists(), "报告目录已存在，拒绝覆盖")
    receipt, content, unchanged = _build(run_dir, references, references_sha256)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cash-price-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "report"
        staged.mkdir()
        for name, data in content.items():
            (staged / name).write_bytes(data)
        unchanged()
        _check(not destination.exists(), "报告目录已存在，拒绝覆盖")
        staged.rename(destination)
    return receipt


def verify_cash_price_bridge(
    run_dir, *, references, references_sha256, report_dir, manifest_sha256
):
    """Recompute from native inputs, then verify every byte and file membership."""
    root = Path(report_dir)
    _check(not root.is_symlink(), "报告目录不能是符号链接")
    _check(
        digest((root / "manifest.json").read_bytes()) == manifest_sha256, "报告清单SHA-256不一致"
    )
    receipt, content, unchanged = _build(run_dir, references, references_sha256)
    _check({p.name for p in root.iterdir()} == set(content), "报告文件集合不一致")
    for name, data in content.items():
        path = root / name
        _check(
            path.is_file() and not path.is_symlink() and path.read_bytes() == data,
            f"报告与原生重算不一致: {name}",
        )
    unchanged()
    return receipt
