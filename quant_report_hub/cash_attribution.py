"""Reconstruct cash-security P&L from the native, immutable QExec journal.

This is accounting attribution, not a replacement for M5's component contract
or a causal decomposition. In particular, fill-price slippage stays in trading
P&L and native unified fees are never invented into commission/tax components.
"""

from __future__ import annotations

import html
import json
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

import pandas as pd

from quant_report_hub.attribution import (
    V2AttributionError,
    _decimal_from_fixed,
    _parse_utc,
    _read_validated_v2,
    _sha256,
)

ZERO = Decimal(0)
ONE = Decimal(1)
LIMITATIONS = [
    "单账户、单策略、同币种、单位乘数的多头现金证券账本；不覆盖保证金、外汇或外部入出金。",
    "估值与成交损益包含成交价格中的滑点；没有独立因果参考价时不拆分滑点。",
    "费用保留原生cost_type；合并费用不拆成佣金和税。",
    "现金本身在本模型中不计息；现金机会成本、信号和风险约束效果需要另做反事实回放。",
    "账本守恒不认证真实市场数据、投资适用性或策略有效性。",
]


def _check(condition, message):
    if not condition:
        raise V2AttributionError(message)


def _fixed(row, field):
    return _decimal_from_fixed(row[field + "_units"], row[field + "_scale"], field)


def _identifier(value):
    return None if pd.isna(value) else str(value)


def _records(frame):
    result = frame.to_dict("records")
    for row in result:
        row["event_time"] = _parse_utc(row["event_time"], "event_time")
    return result


def _unique(rows, field):
    if field != "event_time":
        _check(
            all(isinstance(row[field], str) and row[field].strip() for row in rows),
            f"{field}必须是非空标识",
        )
    result = {row[field]: row for row in rows}
    _check(len(result) == len(rows), f"{field}重复")
    return result


def _sum(rows, account):
    return sum((r["amount"] for r in rows if r["ledger_account"] == account), ZERO)


def _journal(frame):
    transactions = []
    keys = set()
    for transaction_id, group in frame.groupby("transaction_id", sort=False):
        rows = _records(group)
        first = rows[0]
        for key in ("event_time", "event_type", "reference_id", "idempotency_key"):
            _check(all(r[key] == first[key] for r in rows), f"交易{transaction_id}的{key}不一致")
        _check(first["idempotency_key"] not in keys, "现金账本幂等键重复")
        keys.add(first["idempotency_key"])
        _check(sorted(r["posting_index"] for r in rows) == list(range(len(rows))), "分录序号不完整")
        quantities = defaultdict(lambda: ZERO)
        for row in rows:
            row["amount"] = _fixed(row, "amount")
            row["instrument_id"] = _identifier(row["instrument_id"])
            has_units = not pd.isna(row["quantity_delta_units"])
            has_scale = not pd.isna(row["quantity_delta_scale"])
            _check(has_units == has_scale, "数量分录units/scale必须同时存在")
            row["quantity"] = _fixed(row, "quantity_delta") if has_units else ZERO
            if row["ledger_account"] in {"assets:position", "memo:position_counter"}:
                _check(row["amount"] == 0, "数量科目不能混入金额")
            if has_units:
                _check(
                    row["ledger_account"] in {"assets:position", "memo:position_counter"},
                    "非持仓分录携带数量",
                )
                _check(row["instrument_id"] is not None, "数量分录缺少证券")
                quantities[row["instrument_id"]] += row["quantity"]
        _check(sum((r["amount"] for r in rows), ZERO) == 0, "现金账本借贷不平")
        _check(all(q == 0 for q in quantities.values()), "现金账本数量借贷不平")
        transactions.append(
            {
                "id": transaction_id,
                "rows": rows,
                **{k: first[k] for k in ("event_time", "event_type", "reference_id")},
            }
        )
    return sorted(transactions, key=lambda t: (t["event_time"], t["id"]))


def _prepare_transactions(transactions, fills, costs, account, strategy, currency):
    fill_by_id = _unique(fills, "fill_id")
    cost_by_id = _unique(costs, "cost_id")
    seen_fills, seen_costs = set(), set()
    receivable_owner = {}
    # Accrual and payment may share a timestamp. Link by the explicit entitlement
    # key and check chronology, never parse instrument names from an opaque key.
    for tx in transactions:
        if tx["event_type"] != "corporate_action":
            continue
        rows = tx["rows"]
        income = [r for r in rows if r["ledger_account"] == "income:corporate_action"]
        due = [r for r in rows if r["ledger_account"] == "assets:dividend_receivable"]
        if income and due:
            _check(len(income) == len(due) == 1, "分红应收归属不唯一")
            key = due[0]["instrument_id"]
            _check(key is not None and key not in receivable_owner, "分红应收键缺失或重复")
            receivable_owner[key] = (income[0]["instrument_id"], tx["event_time"])
    opening = None
    fee_details = []
    for tx in transactions:
        rows = tx["rows"]
        kind, ref = tx["event_type"], tx["reference_id"]
        accounts = {r["ledger_account"] for r in rows}
        _check(len(accounts) == len(rows), "同一交易中账本科目重复")
        cash = _sum(rows, "assets:cash")
        tx["cash"] = cash
        tx["due"] = {}
        tx["quantity"] = {
            r["instrument_id"]: r["quantity"]
            for r in rows
            if r["ledger_account"] == "assets:position"
        }
        tx["instrument"] = None
        tx["trade_cash"] = tx["corporate_income"] = tx["fee_cash"] = ZERO
        if kind == "fx_conversion":
            _check(
                accounts == {"assets:cash", "equity:opening"} and opening is None,
                "只接受唯一现金期初分录，不支持FX或重复入金",
            )
            _check(cash > 0 and ref == f"opening:{currency}", "期初资金分录无效")
            _check(tx["event_time"] == transactions[0]["event_time"], "期初分录不是最早事件")
            opening = cash
        elif kind == "fill":
            _check(ref in fill_by_id and ref not in seen_fills, "成交分录缺少唯一fill")
            fill = fill_by_id[ref]
            seen_fills.add(ref)
            _check(fill["event_time"] == tx["event_time"], "成交与账本时点不一致")
            quantity, price = _fixed(fill, "quantity"), _fixed(fill, "price")
            _check(
                quantity > 0 and price > 0 and fill["side"] in {"buy", "sell"},
                "成交价格/数量/方向无效",
            )
            sign = ONE if fill["side"] == "buy" else -ONE
            cash_row = next((r for r in rows if r["ledger_account"] == "assets:cash"), None)
            _check(cash_row is not None, "现金成交缺少现金分录")
            expected = (-sign * quantity * price).quantize(
                ONE.scaleb(-int(cash_row["amount_scale"])), rounding=ROUND_HALF_EVEN
            )
            _check(cash == expected, "成交现金不等于单位乘数成交名义金额")
            expected_accounts = {
                "assets:cash",
                "assets:position_cost",
                "assets:position",
                "memo:position_counter",
            }
            if fill["side"] == "sell":
                expected_accounts.add("income:realized_pnl")
            _check(accounts == expected_accounts, "成交分录不是受支持的现金证券结构")
            instrument = fill["instrument_id"]
            _check(tx["quantity"] == {instrument: sign * quantity}, "成交数量与持仓分录不一致")
            _check(
                all(r["instrument_id"] in {None, instrument} for r in rows), "成交分录证券不一致"
            )
            tx["instrument"], tx["trade_cash"] = instrument, cash
        elif kind == "fee":
            _check(accounts == {"assets:cash", "expenses:fees"}, "费用分录结构不受支持")
            _check(ref in cost_by_id and ref not in seen_costs, "费用分录缺少唯一cost")
            cost = cost_by_id[ref]
            seen_costs.add(ref)
            _check(cost["fill_id"] in fill_by_id, "费用不能追溯到成交")
            fill = fill_by_id[cost["fill_id"]]
            _check(cost["instrument_id"] == fill["instrument_id"], "费用和成交证券不一致")
            _check(
                cost["event_time"] == tx["event_time"] >= fill["event_time"],
                "费用时点不一致或先于成交",
            )
            _check(
                isinstance(cost["cost_type"], str) and bool(cost["cost_type"].strip()),
                "原生费用分类为空",
            )
            _check(cash == -_fixed(cost, "amount"), "费用表与现金分录不一致")
            _check(
                all(r["instrument_id"] in {None, cost["instrument_id"]} for r in rows),
                "费用分录证券不一致",
            )
            tx["instrument"], tx["fee_cash"] = cost["instrument_id"], cash
            fee_details.append(
                {
                    "event_time": tx["event_time"],
                    "account_id": account,
                    "strategy_id": strategy,
                    "instrument_id": tx["instrument"],
                    "cost_id": ref,
                    "fill_id": cost["fill_id"],
                    "cost_type": cost["cost_type"],
                    "amount": -cash,
                    "currency": currency,
                }
            )
        elif kind == "corporate_action":
            owners = {
                r["instrument_id"]
                for r in rows
                if r["instrument_id"] is not None
                and r["ledger_account"] != "assets:dividend_receivable"
            }
            for row in rows:
                if row["ledger_account"] == "assets:dividend_receivable":
                    key = row["instrument_id"]
                    _check(key in receivable_owner, "分红应收缺少可追溯的确认分录")
                    owner, accrued_at = receivable_owner[key]
                    _check(
                        owner is not None and accrued_at <= tx["event_time"], "分红到账先于权益确认"
                    )
                    owners.add(owner)
                    tx["due"][key] = row["amount"]
            _check(len(owners) == 1, "公司行动证券归属不唯一")
            tx["instrument"] = owners.pop()
            quantity_accounts = {"assets:position", "memo:position_counter"}
            if "assets:position_cost" in accounts:
                _check(
                    accounts
                    == quantity_accounts
                    | {"assets:cash", "assets:position_cost", "income:realized_pnl"},
                    "终止兑付分录结构不受支持",
                )
                _check(all(q <= 0 for q in tx["quantity"].values()), "终止兑付不能增加持仓")
                tx["trade_cash"] = cash
            else:
                monetary = accounts - quantity_accounts
                _check(
                    monetary
                    in (
                        set(),
                        {"assets:cash", "income:corporate_action"},
                        {"assets:dividend_receivable", "income:corporate_action"},
                        {"assets:cash", "assets:dividend_receivable"},
                    ),
                    "公司行动分录结构不受支持",
                )
                tx["corporate_income"] = cash + sum(tx["due"].values(), ZERO)
        else:
            raise V2AttributionError(f"现金归因不支持账本事件: {kind}")
    _check(opening is not None, "缺少可核验的现金期初资金")
    _check(seen_fills == set(fill_by_id), "有成交未记入账本")
    _check(seen_costs == set(cost_by_id), "有费用未记入账本")
    return opening, receivable_owner, fee_details


def _reconstruct(manifest, frames):
    required = {
        "cash_ledger",
        "positions",
        "portfolio_snapshots",
        "fills",
        "costs",
        "returns",
        "margin",
    }
    _check(not required - frames.keys(), f"现金归因缺少产物: {sorted(required - frames.keys())}")
    _check(
        manifest.profile == "backtest-ledger" and len(manifest.strategy_ids) == 1,
        "现金归因需要单策略backtest-ledger产物",
    )
    snapshots = _records(frames["portfolio_snapshots"])
    _check(bool(snapshots), "持仓快照为空")
    account = snapshots[0]["account_id"]
    strategy, currency = manifest.strategy_ids[0], manifest.base_currency
    for name in required:
        frame = frames[name]
        for field, expected in (
            ("account_id", account),
            ("strategy_id", strategy),
            ("currency", currency),
            ("base_currency", currency),
        ):
            if field in frame:
                _check(
                    frame[field].eq(expected).fillna(False).all(),
                    f"{name}.{field}不是单账户/策略/币种",
                )
    for row in _records(frames["margin"]):
        _check(
            row["initial_margin_units"] == row["maintenance_margin_units"] == 0,
            "现金归因不支持保证金",
        )
    snapshots.sort(key=lambda r: r["event_time"])
    snapshot_by_time = _unique(snapshots, "event_time")
    returns = sorted(_records(frames["returns"]), key=lambda r: r["event_time"])
    _check(bool(returns), "收益边界为空")
    return_by_time = _unique(returns, "event_time")
    _check(set(return_by_time) <= set(snapshot_by_time), "收益边界缺少精确时点快照")
    _check(returns[-1]["event_time"] == snapshots[-1]["event_time"], "收益边界未覆盖最后快照")
    positions = defaultdict(dict)
    for row in _records(frames["positions"]):
        stamp, instrument = row["event_time"], row["instrument_id"]
        _check(
            stamp in snapshot_by_time and instrument not in positions[stamp],
            "持仓快照缺失或证券重复",
        )
        qty, price, value = (
            _fixed(row, "quantity"),
            _fixed(row, "mark_price"),
            _fixed(row, "market_value"),
        )
        expected = (qty * price).quantize(
            ONE.scaleb(-int(row["market_value_scale"])), rounding=ROUND_HALF_EVEN
        )
        _check(qty >= 0 and price > 0 and _fixed(row, "fx_rate") == 1, "不支持空头、无效估值或FX")
        _check(
            value == expected == _fixed(row, "base_market_value"),
            "持仓估值与单位乘数数量价格不一致",
        )
        positions[stamp][instrument] = (qty, value)
    transactions = _journal(frames["cash_ledger"])
    _check(bool(transactions), "现金账本为空")
    opening, due_owner, fees = _prepare_transactions(
        transactions,
        _records(frames["fills"]),
        _records(frames["costs"]),
        account,
        strategy,
        currency,
    )
    _check(transactions[-1]["event_time"] <= snapshots[-1]["event_time"], "快照未覆盖最后账本事件")
    cash, previous_nav = ZERO, opening
    quantities, due = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    previous_values = {}
    totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    details, periods, events = [], [], []
    cursor = 0
    period_opening = opening
    for snapshot in snapshots:
        stamp = snapshot["event_time"]
        changes = defaultdict(lambda: defaultdict(lambda: ZERO))
        while cursor < len(transactions) and transactions[cursor]["event_time"] <= stamp:
            tx = transactions[cursor]
            cursor += 1
            cash += tx["cash"]
            for instrument, quantity in tx["quantity"].items():
                quantities[instrument] += quantity
            for key, amount in tx["due"].items():
                due[key] += amount
            if tx["instrument"] is not None:
                for field in ("trade_cash", "corporate_income", "fee_cash"):
                    changes[tx["instrument"]][field] += tx[field]
        _check(
            cash >= 0
            and all(q >= 0 for q in quantities.values())
            and all(v >= 0 for v in due.values()),
            "现金、持仓或应收余额为负",
        )
        current = positions[stamp]
        _check(
            {i: q for i, q in quantities.items() if q}
            == {i: v[0] for i, v in current.items() if v[0]},
            "持仓数量与完整账本不一致",
        )
        market = sum((v[1] for v in current.values()), ZERO)
        receivable = sum(due.values(), ZERO)
        nav = _fixed(snapshot, "nav")
        _check(_fixed(snapshot, "margin_used") == 0, "快照包含保证金")
        _check(cash == _fixed(snapshot, "cash_value"), "现金余额与快照不一致")
        _check(market == _fixed(snapshot, "market_value"), "证券估值合计与快照不一致")
        _check(nav == cash + market + receivable, "NAV不等于现金、持仓估值与分红应收合计")
        event_pnl = ZERO
        for instrument in sorted(set(previous_values) | set(current) | set(changes)):
            start = previous_values.get(instrument, ZERO)
            end = current.get(instrument, (ZERO, ZERO))[1]
            change = changes[instrument]
            valuation = end - start + change["trade_cash"]
            pnl = valuation + change["corporate_income"] + change["fee_cash"]
            event_pnl += pnl
            result = totals[instrument]
            if "opening_market_value" not in result:
                result["opening_market_value"] = start
            result["closing_market_value"] = end
            result["valuation_and_trading_pnl"] += valuation
            result["net_pnl"] += pnl
            for field in ("trade_cash", "corporate_income", "fee_cash"):
                result[field] += change[field]
        _check(nav - previous_nav == event_pnl, "事件损益与NAV变化不一致")
        events.append(
            {
                "event_time": stamp,
                "cash": cash,
                "market_value": market,
                "dividend_receivable": receivable,
                "nav": nav,
                "net_pnl": event_pnl,
                "residual": ZERO,
                "status": "pass",
            }
        )
        previous_values = {i: value for i, (_, value) in current.items()}
        previous_nav = nav
        if stamp in return_by_time:
            ret = return_by_time[stamp]
            _check(period_opening > 0, "非正期初NAV不能换算收益贡献")
            _check(_fixed(ret, "nav") == nav, "收益表NAV与快照不一致")
            rate = Decimal(str(ret["net_return"]))
            expected_rate = nav / period_opening - 1
            _check(
                rate.is_finite() and abs(rate - expected_rate) <= Decimal("1e-12"),
                "净收益率与NAV路径不一致",
            )
            period_pnl = sum((r["net_pnl"] for r in totals.values()), ZERO)
            _check(period_pnl == nav - period_opening, "期间证券损益合计与账户不一致")
            for instrument, result in sorted(totals.items()):
                details.append(
                    {
                        "event_time": stamp,
                        "account_id": account,
                        "strategy_id": strategy,
                        "instrument_id": instrument,
                        **dict(result),
                        "return_contribution": result["net_pnl"] / period_opening,
                        "currency": currency,
                    }
                )
            periods.append(
                {
                    "event_time": stamp,
                    "opening_nav": period_opening,
                    "closing_nav": nav,
                    "cash": cash,
                    "market_value": market,
                    "dividend_receivable": receivable,
                    "valuation_and_trading_pnl": sum(
                        (r["valuation_and_trading_pnl"] for r in totals.values()), ZERO
                    ),
                    "corporate_income": sum((r["corporate_income"] for r in totals.values()), ZERO),
                    "fee_cash": sum((r["fee_cash"] for r in totals.values()), ZERO),
                    "net_pnl": period_pnl,
                    "source_net_return": rate,
                    "net_return": expected_rate,
                    "residual": ZERO,
                    "status": "pass",
                }
            )
            totals.clear()
            period_opening = nav
    _check(cursor == len(transactions), "账本事件未全部消费")
    _check(not totals, "最后收益边界之外存在未归因损益")
    return {
        "instrument_pnl.csv": pd.DataFrame(
            details,
            columns=[
                "event_time",
                "account_id",
                "strategy_id",
                "instrument_id",
                "opening_market_value",
                "closing_market_value",
                "trade_cash",
                "valuation_and_trading_pnl",
                "corporate_income",
                "fee_cash",
                "net_pnl",
                "return_contribution",
                "currency",
            ],
        ),
        "period_reconciliation.csv": pd.DataFrame(periods),
        "event_reconciliation.csv": pd.DataFrame(events),
        "fee_details.csv": pd.DataFrame(
            fees,
            columns=[
                "event_time",
                "account_id",
                "strategy_id",
                "instrument_id",
                "cost_id",
                "fill_id",
                "cost_type",
                "amount",
                "currency",
            ],
        ),
    }, {
        "account_id": account,
        "strategy_id": strategy,
        "currency": currency,
        "opening_nav": str(opening),
        "closing_nav": str(previous_nav),
        "net_pnl": str(previous_nav - opening),
        "valuation_and_trading_pnl": str(
            sum((r["valuation_and_trading_pnl"] for r in periods), ZERO)
        ),
        "corporate_income": str(sum((r["corporate_income"] for r in periods), ZERO)),
        "fee_cash": str(sum((r["fee_cash"] for r in periods), ZERO)),
        "first_period_end": returns[0]["event_time"].isoformat(),
        "last_period_end": returns[-1]["event_time"].isoformat(),
        "transactions_checked": len(transactions),
        "entitlements_checked": len(due_owner),
    }


def reconcile_cash_ledger_v2(run_dir: str | Path, *, out_dir: str | Path) -> dict:
    """Validate every journal event before publishing a separate accounting report."""
    run_path, manifest, frames, source_hash = _read_validated_v2(run_dir)
    destination = Path(out_dir).resolve()
    source = run_path.resolve()
    _check(
        destination != source and source not in destination.parents, "报告必须位于源运行目录之外"
    )
    if destination.exists():
        raise FileExistsError(f"报告目录已存在，拒绝覆盖: {destination}")
    with localcontext() as context:
        context.prec = 80
        tables, summary = _reconstruct(manifest, frames)
    # No output is created until all input, accounting and return checks pass.
    destination.mkdir(parents=True, exist_ok=False)
    for name, table in tables.items():
        table.to_csv(destination / name, index=False, encoding="utf-8", lineterminator="\n")
    table = tables["period_reconciliation.csv"]
    rows = table[
        [
            "event_time",
            "valuation_and_trading_pnl",
            "corporate_income",
            "fee_cash",
            "net_pnl",
            "residual",
        ]
    ].copy()
    rows.columns = ["期间结束", "估值与成交损益", "公司行动收益", "费用现金影响", "净损益", "残差"]
    page = (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>现金证券账本归因</title>'
        "<style>body{font:16px system-ui;margin:32px;color:#182537;max-width:1100px}"
        "table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #ccd3dc;text-align:right}"
        "th:first-child,td:first-child{text-align:left}.scroll{overflow-x:auto}li{margin:8px 0}</style>"
        "<h1>现金证券账本归因</h1><p>逐事件重建现金、持仓数量、估值与分红应收；按来源收益边界汇总。</p>"
        f"<p>运行：{html.escape(manifest.run_id)}；币种：{html.escape(manifest.base_currency)}；"
        f"事件快照：{len(tables['event_reconciliation.csv'])}；收益期间：{len(table)}。全部对账通过。</p>"
        f"<p>期初净值：{html.escape(summary['opening_nav'])}；期末净值：{html.escape(summary['closing_nav'])}；"
        f"净损益：{html.escape(summary['net_pnl'])}。</p>"
        f"<p>估值与成交损益：{html.escape(summary['valuation_and_trading_pnl'])}；"
        f"公司行动收益：{html.escape(summary['corporate_income'])}；费用现金影响：{html.escape(summary['fee_cash'])}。</p>"
        "<p>净损益=估值与成交损益+公司行动收益+费用现金影响。费用现金影响通常为负。</p><ul>"
        + "".join(f"<li>{html.escape(item)}</li>" for item in LIMITATIONS)
        + "</ul><p>"
        + " · ".join(f'<a href="{name}">{name}</a>' for name in tables)
        + '</p><div class="scroll">'
        + rows.to_html(index=False, border=0, escape=True)
        + "</div></html>"
    )
    (destination / "report.html").write_text(page, encoding="utf-8")
    result = {
        "schema_version": "quant-report-hub.cash-ledger-attribution/v1",
        "source_run_manifest_sha256": source_hash,
        "source_run_id": manifest.run_id,
        "source_project": manifest.project,
        "source_code_version": manifest.code_version,
        "summary": summary,
        "limitations": LIMITATIONS,
        "semantics": {
            "period_boundaries": "source returns.event_time",
            "opening_capital": "equity:opening journal transaction",
            "valuation_and_trading_pnl": "delta market value + signed trade/terminal cash",
            "corporate_income": "dividend cash + change in dividend receivable",
            "fee_cash": "native fee cash postings; signed, unclassified",
            "return_contribution": "instrument net P&L / period opening NAV",
        },
        "row_counts": {name: len(table) for name, table in tables.items()},
        "files": {name: _sha256(destination / name) for name in [*tables, "report.html"]},
    }
    (destination / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return result
