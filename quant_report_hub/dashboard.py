"""Publish a local, self-contained research dashboard without changing inputs."""

from __future__ import annotations

import html
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from quant_report_hub.dashboard_assets import CSS, SCRIPT
from quant_report_hub.dashboard_data import dashboard_snapshot

LABELS = {
    "paper_ready": "可继续模拟",
    "observe": "仅观察",
    "blocked": "运行阻断",
    "invalid": "来源不可用",
    "expired": "已过期 · 仅供复盘",
}
FIELDS = {
    "symbol": "证券",
    "account_id": "账户",
    "quantity": "数量",
    "weight": "权重",
    "order_id": "订单编号",
    "side": "方向",
    "reference_close": "参考收盘",
    "estimated_execution_price": "预计成交价",
    "estimated_fee": "预计费用",
    "estimated_slippage": "预计滑点",
    "market_value": "市值",
    "change_type": "变化",
    "previous_quantity": "上次数量",
    "target_quantity": "本次数量",
    "quantity_change": "数量变化",
    "previous_weight": "上次权重",
    "target_weight": "本次权重",
    "weight_change": "权重变化",
    "planned_quantity": "计划数量",
    "order_quantity": "订单数量",
    "filled_quantity": "成交数量",
    "fill_rate": "完成比例",
    "order_status": "订单状态",
    "average_fill_price": "平均成交价",
    "price_difference": "成交价－预计价",
    "actual_cost": "实际成本",
    "currency": "币种",
    "last_event_at": "最后事件时间",
    "event_time": "持仓时间",
    "evidence_check": "证据核对",
    "source": "来源",
    "project": "项目",
    "strategies": "策略",
    "status": "状态",
    "nav": "净值",
    "cash": "现金",
    "planned_orders": "计划订单",
    "filled_orders": "已成交订单",
    "alerts": "需处理异常",
    "as_of": "数据截至",
}

CHANGE_LABELS = {
    "new": "新增",
    "exit": "退出",
    "increase": "增持",
    "decrease": "减持",
    "unchanged": "不变",
}
ORDER_LABELS = {
    "created": "已创建",
    "accepted": "已接受 · 待成交",
    "partially_filled": "部分成交",
    "filled": "全部成交",
    "rejected": "已拒绝",
    "cancelled": "已取消",
    "expired": "已失效",
    "source_missing": "订单证据缺失",
}
ALERT_LABELS = {"critical": "严重", "warning": "提醒", "info": "进度"}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def number(value, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if isinstance(value, int) and not percent:
            return f"{value:,}"
        return f"{value:.2%}" if percent else f"{value:,.2f}"
    return esc(value)


def detail(title: str, value) -> str:
    return f'<details class="details"><summary>{esc(title)}</summary><pre>{esc(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>'


def rows_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="empty">暂无记录</p>'
    keys = list(dict.fromkeys(key for row in rows for key in row))
    header = "".join(f"<th>{esc(FIELDS.get(key, key))}</th>" for key in keys)

    def cell(key, value):
        if key == "side" and isinstance(value, str):
            return {"buy": "模拟买入", "sell": "模拟卖出"}.get(value, esc(value))
        if key in {"weight", "previous_weight", "target_weight", "weight_change", "fill_rate"}:
            return number(value, percent=True)
        if key == "change_type":
            return esc(CHANGE_LABELS.get(value, value))
        if key == "order_status":
            return esc(ORDER_LABELS.get(value, value))
        if key in {
            "quantity",
            "previous_quantity",
            "target_quantity",
            "quantity_change",
            "planned_quantity",
            "order_quantity",
            "filled_quantity",
        } and isinstance(value, (float, int)):
            return f"{value:,.4f}".rstrip("0").rstrip(".")
        return number(value)

    body = "".join(
        "<tr>" + "".join(f"<td>{cell(key, row.get(key))}</td>" for key in keys) + "</tr>"
        for row in rows
    )
    return f'<div class="scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def _link(path: Path, label: str, out: Path) -> str:
    if not path.is_file():
        return ""
    try:
        href = quote(
            Path(os.path.relpath(path.resolve(), out.parent.resolve())).as_posix(), safe="/"
        )
    except ValueError:  # Different Windows drives require a file URI.
        href = path.resolve().as_uri()
    return f'<a href="{esc(href)}">{esc(label)}</a>'


def evidence_links(run: Path, out: Path) -> str:
    files = [
        ("decision.json", "决策 JSON"),
        ("standard/v2/run_manifest.json", "账本清单"),
        ("standard/v2/config.json", "运行配置"),
        ("standard/v2/metrics.json", "原始指标"),
        ("standard/v2/orders.parquet", "订单"),
        ("standard/v2/order_events.parquet", "订单事件"),
        ("standard/v2/fills.parquet", "成交"),
        ("standard/v2/costs.parquet", "实际成本"),
        ("standard/v2/positions.parquet", "实际持仓"),
        ("standard/v2/returns.parquet", "收益序列"),
        ("standard/v2/cash_ledger.parquet", "现金账本"),
        ("experiment.json", "实验登记"),
        ("validation_folds.csv", "验证窗口"),
        ("validation_fdr.csv", "因子检验"),
    ]
    return (
        '<div class="evidence">'
        + "".join(_link(run / p, label, out) for p, label in files)
        + "</div>"
    )


def _identity_text(item: dict) -> str:
    identity = item.get("identity", {})
    values = []
    if identity.get("project"):
        values.append(f"项目 {esc(identity['project'])}")
    if identity.get("strategies"):
        values.append("策略 " + esc("、".join(identity["strategies"])))
    if identity.get("accounts"):
        values.append("账户 " + esc("、".join(identity["accounts"])))
    return " · ".join(values)


def _change_panel(item: dict) -> str:
    change = item.get("change", {})
    if not change:
        return ""
    parts = ['<section class="review-block"><div class="block-head"><h4>与上次决策相比</h4>']
    if change.get("previous_run_id"):
        parts.append(f'<span class="run-id">基准 {esc(change["previous_run_id"])}</span>')
    parts.append("</div>")
    tone = "notice" if change.get("available") else "notice neutral"
    parts.append(f'<p class="{tone}">{esc(change.get("summary", "暂无比较基准"))}</p>')
    flags = []
    if change.get("config_changed"):
        flags.append("运行配置已变化")
    if change.get("code_changed"):
        flags.append("代码版本已变化")
    if flags:
        parts.append('<p class="meta">' + " · ".join(flags) + "</p>")
    if change.get("rows"):
        parts.append(rows_table(change["rows"]))
    return "".join(parts) + "</section>"


def _execution_panel(item: dict) -> str:
    execution = item.get("execution", {})
    if not execution:
        return ""
    metrics = (
        ("计划订单", execution.get("planned_orders")),
        ("找到订单证据", execution.get("matched_orders")),
        ("已有成交的订单", execution.get("orders_with_fills")),
        ("成交记录", execution.get("fill_records")),
    )
    parts = [
        '<section class="review-block"><div class="block-head"><h4>计划与实际执行</h4><span class="meta">来自已校验 standard/v2 账本</span></div>',
        '<div class="mini-metrics">'
        + "".join(
            f"<div><span>{label}</span><b>{number(value)}</b></div>" for label, value in metrics
        )
        + "</div>",
    ]
    if execution.get("notice"):
        parts.append(f'<p class="notice warning">{esc(execution["notice"])}</p>')
    if execution.get("orders"):
        visible = [
            {
                key: row.get(key)
                for key in (
                    "symbol",
                    "side",
                    "planned_quantity",
                    "filled_quantity",
                    "fill_rate",
                    "order_status",
                    "estimated_execution_price",
                    "average_fill_price",
                    "price_difference",
                    "actual_cost",
                    "currency",
                    "evidence_check",
                )
            }
            for row in execution["orders"]
        ]
        parts.append(rows_table(visible))
    costs = execution.get("actual_costs", [])
    if costs:
        text = "、".join(f"{number(row['amount'])} {esc(row['currency'])}" for row in costs)
        parts.append(f'<p class="meta">实际账本成本：{text}</p>')
    parts.append('<details class="details"><summary>查看执行后的模拟持仓</summary>')
    parts.append(rows_table(execution.get("positions", [])))
    parts.append("</details></section>")
    return "".join(parts)


def _outcome_panel(item: dict) -> str:
    outcome = item.get("outcome", {})
    if not outcome:
        return ""
    windows = outcome.get("windows", [])
    metrics = [(f"{row['days']} 日", number(row.get("return"), percent=True)) for row in windows]
    metrics.extend(
        [
            ("已观察累计", number(outcome.get("observed_return"), percent=True)),
            ("同期基准累计", number(outcome.get("benchmark_return"), percent=True)),
        ]
    )
    parts = [
        '<section class="review-block"><div class="block-head"><h4>前向效果跟踪</h4>',
        f'<span class="meta">已成熟 {number(outcome.get("observed_days"))} 个交易日</span></div>',
        '<div class="outcome-grid">'
        + "".join(f"<div><span>{label}</span><b>{value}</b></div>" for label, value in metrics)
        + "</div>",
    ]
    if outcome.get("notice"):
        tone = "notice" if outcome.get("available") else "notice neutral"
        parts.append(f'<p class="{tone}">{esc(outcome["notice"])}</p>')
    parts.append(
        '<p class="meta">窗口值仅在生产者声明足够前向观察日、且标准净收益序列满足一日一条时计算。</p></section>'
    )
    return "".join(parts)


def _risk_panel(item: dict) -> str:
    risk = item.get("risk_summary", {})
    if not risk or not risk.get("available"):
        return ""
    values = []
    for metric in risk.get("metrics", []):
        value = metric.get("value")
        if metric.get("kind") == "percent":
            formatted = number(value, percent=True)
        elif metric.get("kind") == "bps":
            formatted = "—" if value is None else f"{value:,.2f} bps"
        else:
            formatted = number(value)
        suffix = metric.get("currency", "")
        values.append(
            f"<div><span>{esc(metric['label'])}</span><b>{formatted}</b>"
            f"{f'<small>{esc(suffix)}</small>' if suffix else ''}</div>"
        )
    parts = [
        '<section class="review-block"><div class="block-head"><h4>风险摘要</h4>',
        '<span class="meta">由生产者限制、目标持仓和已观察指标直接计算</span></div>',
        '<div class="risk-grid">' + "".join(values) + "</div>",
    ]
    for breach in risk.get("breaches", []):
        tone = "error" if breach["severity"] == "critical" else "warning"
        parts.append(f'<p class="notice {tone}">{esc(breach["message"])}</p>')
    return "".join(parts) + "</section>"


def alerts_panel(alerts: list[dict], out: Path) -> str:
    if not alerts:
        return '<p class="notice">当前快照没有需要处理的异常。</p>'
    rows = []
    for alert in alerts:
        link = _link(Path(alert["evidence"]), "证据", out) if alert.get("evidence") else ""
        search = " ".join(
            str(alert.get(key, "")) for key in ("source", "project", "run_id", "code", "message")
        )
        rows.append(
            f'<tr data-search="{esc(search)}" data-status="{esc(alert["severity"])}" '
            f'data-source="{esc(alert.get("source_id", ""))}">'
            f'<td><span class="alert-badge {esc(alert["severity"])}">'
            f"{esc(ALERT_LABELS.get(alert['severity'], alert['severity']))}</span></td>"
            f'<td><b>{esc(alert["source"])}</b><br><span class="run-id">{esc(alert["run_id"])}</span></td>'
            f"<td>{esc(alert['message'])}</td><td><code>{esc(alert['code'])}</code>{link}</td></tr>"
        )
    return (
        '<div class="scroll alerts"><table><thead><tr><th>级别</th><th>来源／运行</th>'
        "<th>说明</th><th>代码／证据</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def accounts_panel(accounts: list[dict]) -> str:
    visible = []
    for row in accounts:
        rendered = dict(row)
        rendered["status"] = LABELS.get(row["status"], row["status"])
        visible.append(rendered)
    return rows_table(visible)


def decision_panel(item: dict, out: Path) -> str:
    card = item["card"]
    status = item["status"]
    current = item["latest"]
    title = Path(item["root"]).name
    eligible = current and status == "paper_ready"
    source_id = item.get("source_id", "")
    identity_text = _identity_text(item)
    trade_count = len(card.get("proposed_trades", [])) if card else 0
    deadline = card.get("valid_until") or ""
    expirable = status in {"paper_ready", "observe", "expired"}
    parts = [
        f'''<article class="card" {f'id="decision-{esc(source_id)}"' if current else ""} data-decision-card data-search="{esc(title + " " + item["run_id"] + " " + identity_text)}" data-status="{esc(status)}" data-source="{esc(source_id)}"
      data-latest="{str(current).lower()}" data-valid-until="{esc(deadline)}" data-expirable="{str(expirable).lower()}" data-eligible="{str(eligible).lower()}" data-trade-count="{trade_count}">
      <div class="card-head"><div><h3>{esc(title)}{" · 历史运行" if not current else ""}</h3><div class="run-id">{esc(item["run_id"])}</div></div>
      <span class="badge {esc(status)}" data-status-badge>{"历史状态：" if not current else ""}{LABELS[status]}</span></div>'''
    ]
    if item["error"]:
        parts.append(
            f'<p class="notice error">{esc(item["error"])}</p><p class="muted">无法确认本次结果，不使用历史成功运行替代。</p>'
        )
    elif card:
        parts.append(
            f'<p class="meta">行情截至 {esc(card["as_of"])} · 有效期至 {esc(deadline or "—")}</p>'
        )
        if identity_text:
            parts.append(f'<p class="identity">{identity_text}</p>')
        parts.append(
            '<p class="notice">虚拟模拟账户 · 研究有效性尚待验证。可继续模拟不代表已证明策略适合真实投资。</p>'
        )
        parts.append(
            f'<p class="notice warning" data-expiry-notice {"" if status == "expired" else "hidden"}>此决策已过期，拟调仓已隐藏。刷新数据并重新生成看板。</p>'
        )
        parts.append(
            '<ul class="meta">'
            + "".join(f"<li>{esc(reason)}</li>" for reason in card["reasons"])
            + "</ul>"
        )
        validation = card["validation"]
        cost = card["estimated_cost"]
        parts.append(
            '<div class="metrics">'
            + "".join(
                f"<div><span>{label}</span><b>{value}</b></div>"
                for label, value in (
                    ("目标标的", number(len(card["targets"]))),
                    ("拟调仓", number(len(card["proposed_trades"]))),
                    ("预计总成本", f"{number(cost.get('total'))} {esc(cost.get('currency', ''))}"),
                    ("前向观察天数", number(validation.get("forward_observation_days"))),
                )
            )
            + "</div>"
        )
        parts.append("<h4>当前模拟持仓</h4>" + rows_table(card["current_positions"]))
        if eligible:
            parts.append(
                "<section data-paper-actions hidden><h4>拟模拟调仓 · 下一交易日</h4>"
                + rows_table(
                    [
                        {
                            key: value
                            for key, value in row.items()
                            if key not in {"order_id", "execution"}
                        }
                        for row in card["proposed_trades"]
                    ]
                )
            )
            parts.append(
                f'<p class="meta">预计费用 {number(cost.get("fees"))} + 预计滑点 {number(cost.get("slippage"))} = {number(cost.get("total"))} {esc(cost.get("currency", ""))}（来源估计值）</p>'
            )
            parts.append(detail("目标模拟持仓", card["targets"]) + "</section>")
        else:
            parts.append('<p class="muted">本页不展示可操作的拟调仓；历史记录保留供复盘。</p>')
        if current:
            parts.append(_change_panel(item))
        parts.append(_execution_panel(item))
        parts.append(_outcome_panel(item))
        parts.append(_risk_panel(item))
        parts.append(
            '<div class="columns">'
            + detail("风险与约束", card["risk"])
            + detail("数据质量与来源", card["data_quality"])
            + "</div>"
        )
        parts.append(
            '<div class="columns">'
            + detail("研究验证与基准", validation)
            + detail("版本与血缘", card["evidence"])
            + "</div>"
        )
    if item["path"]:
        parts.append(evidence_links(Path(item["path"]).parent, out))
    return "".join(parts) + "</article>"


def decision_inbox(sources: list[dict]) -> str:
    rows = []
    priority = {"invalid": 0, "blocked": 1, "expired": 2, "paper_ready": 3, "observe": 4}
    ordered = sorted(sources, key=lambda source: priority.get(source["current"]["status"], 9))
    for source in ordered:
        item = source["current"]
        card = item["card"]
        identity = item.get("identity", {})
        source_id = source["source_id"]
        title = Path(source["root"]).name
        status = item["status"]
        deadline = card.get("valid_until", "") if card else ""
        expirable = status in {"paper_ready", "observe", "expired"}
        trade_count = len(card.get("proposed_trades", [])) if card else 0
        project = identity.get("project") or title
        strategies = "、".join(identity.get("strategies", [])) or "—"
        change = item.get("change", {}).get("summary", "暂无比较基准")
        execution = item.get("execution", {})
        if trade_count:
            execution_text = f"{execution.get('orders_with_fills', 0)} / {trade_count} 笔已有成交"
        else:
            execution_text = "无拟调仓"
        search_text = " ".join((title, item["run_id"], project, strategies))
        rows.append(
            f'''<tr data-search="{esc(search_text)}" data-status="{esc(status)}" data-source="{esc(source_id)}"
              data-latest="true" data-valid-until="{esc(deadline)}" data-expirable="{str(expirable).lower()}" data-eligible="{str(status == "paper_ready").lower()}" data-trade-count="{trade_count}">
              <td><a class="decision-link" href="#decision-{esc(source_id)}"><b>{esc(project)}</b></a><br><span class="run-id">{esc(item["run_id"])}</span></td>
              <td>{esc(strategies)}</td><td><span class="badge {esc(status)}" data-status-badge>{LABELS[status]}</span></td>
              <td>{number(trade_count)}</td><td>{esc(change)}</td><td>{esc(execution_text)}</td>
              <td><small>{esc(deadline or "—")}</small></td></tr>'''
        )
    if not rows:
        return '<p class="empty">尚未连接决策目录。</p>'
    return (
        '<div class="scroll inbox"><table><thead><tr><th>项目／运行</th><th>策略</th><th>状态</th><th>拟调仓</th><th>与上次相比</th><th>执行进度</th><th>有效期</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
    )


def experiment_panels(rows: list[dict], out: Path) -> tuple[str, str]:
    body, comparisons = [], []
    for index, row in enumerate(rows):
        label = (
            "来源不可用"
            if row["error"]
            else "产物已校验"
            if row["verified"]
            else "索引缓存 · 未校验"
        )
        status = "invalid" if row["error"] else "verified" if row["verified"] else "cached"
        checkbox = f'<input class="check experiment-check" type="checkbox" value="{index}" aria-label="选择 {esc(row["project"])} / {esc(row["run_id"])}" {"disabled" if row["error"] else ""}>'
        links = evidence_links(Path(row["run_path"]), out)
        body.append(
            f'<tr data-search="{esc(row["project"] + " " + row["run_id"])}" data-status="{status}"><td>{checkbox}</td><td><b>{esc(row["project"])}</b><br><span class="run-id">{esc(row["run_id"])}</span></td><td>{esc(row["run_type"])}</td><td>{label}<br><small>{esc(row["error"])}</small></td><td><small>{esc(row["scanned_at"])}</small>{links}</td></tr>'
        )
        metrics = row["metrics"]
        stat_rows = metrics.get("backtest_stats")
        if not isinstance(stat_rows, list) or not all(isinstance(v, dict) for v in stat_rows):
            stat_rows = [metrics]
        cells = []
        for stats in stat_rows:
            cells.append(
                {
                    "组合／策略": stats.get("portfolio", metrics.get("strategy", "未提供")),
                    "累计收益": number(stats.get("total_return"), percent=True),
                    "年化收益": number(stats.get("ann_return"), percent=True),
                    "Sharpe": number(stats.get("sharpe")),
                    "最大回撤": number(stats.get("max_drawdown"), percent=True),
                }
            )
        comparisons.append(
            f'<article class="card" data-comparison="{index}" hidden><h3>{esc(row["project"])} / {esc(row["run_id"])}</h3><p class="meta">{label} · 指标读取原始产物，缺失值保持为空</p>{rows_table(cells)}{links}{detail("全部来源指标与口径", metrics)}</article>'
        )
    table = (
        '<div class="scroll"><table><thead><tr><th>选择</th><th>项目／运行</th><th>运行类型</th><th>来源状态</th><th>索引时间与证据</th></tr></thead><tbody>'
        + "".join(body)
        + "</tbody></table></div>"
    )
    return table if rows else '<p class="empty">尚无可浏览的实验。</p>', "".join(comparisons)


def render_dashboard(snapshot: dict, out: Path) -> str:
    sources = snapshot["sources"]
    current = "".join(decision_panel(source["current"], out) for source in sources)
    inbox = decision_inbox(sources)
    history = []
    for source in sources:
        history.append(
            f'<details class="history"><summary>{esc(Path(source["root"]).name)} · {len(source["history"])} 条历史记录（最多展示 200 条）</summary>'
            + "".join(decision_panel(item, out) for item in source["history"])
            + "</details>"
        )
    experiments, comparisons = experiment_panels(snapshot["experiments"], out)
    alerts = alerts_panel(snapshot.get("alerts", []), out)
    accounts = accounts_panel(snapshot.get("accounts", []))
    bad = sum(
        source["current"]["status"] in {"invalid", "blocked", "expired"} for source in sources
    )
    active_trades = sum(
        len(source["current"]["card"].get("proposed_trades", []))
        for source in sources
        if source["current"]["status"] == "paper_ready" and source["current"]["card"]
    )
    fills = sum(source["current"].get("execution", {}).get("fill_records", 0) for source in sources)
    severe = sum(alert["severity"] == "critical" for alert in snapshot.get("alerts", []))
    cards = (
        ("—", "当前可继续模拟", "ready-count"),
        (bad, "需处理的最新运行", "attention-count"),
        (active_trades, "有效拟调仓", "active-trade-count"),
        (fills, "模拟成交记录", "fill-count"),
        (severe, "严重异常", "critical-count"),
    )
    stats = "".join(
        f'<div class="stat"><strong id="{c[2] if len(c) == 3 else "stat-" + str(i)}">{c[0]}</strong><span>{c[1]}</span></div>'
        for i, c in enumerate(cards)
    )
    source_options = "".join(
        f'<option value="{esc(source["source_id"])}">{esc(Path(source["root"]).name)}</option>'
        for source in sources
    )
    status_file = out.with_suffix(out.suffix + ".status.json").name
    return f"""<!doctype html><html lang="zh-CN" data-build-id="{esc(snapshot["generated_at"])}" data-refresh-url="{esc(status_file)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Quant Report Hub · 决策看板</title><style>{CSS}</style></head>
<body><div class="shell"><header><div class="brand"><b>Q</b>quant-report-hub</div><nav aria-label="主导航"><a href="#decisions">决策收件箱</a><a href="#alerts">风险与异常</a><a href="#accounts">账户汇总</a><a href="#current-details">决策详情</a><a href="#experiments">实验与对比</a><a href="#history">历史记录</a></nav></header>
<main><section class="hero"><div><p class="eyebrow">RESEARCH / PAPER / EVIDENCE</p><h1>先处理异常，再核对调仓。</h1><p class="intro">集中查看最新决策、相对变化、模拟执行和前向效果；所有数值都来自只读研究产物。</p></div><div class="meta">{len(sources)} 个决策目录 · {len(snapshot["experiments"])} 个实验<br>快照生成于 {esc(snapshot["generated_at"])}<br><span data-refresh-state>静态快照</span></div></section>
<div class="stats">{stats}</div><noscript><p class="notice warning">启用 JavaScript 后可筛选、对比及检查实时有效期。拟调仓默认隐藏；其他来源信息仍可阅读。</p></noscript>
<div class="toolbar"><label>搜索 <input id="search" type="search" placeholder="项目、策略或运行编号"></label><label>来源 <select id="source-filter"><option value="all">全部来源</option>{source_options}</select></label><label>状态 <select id="status-filter"><option value="all">全部状态</option><option value="paper_ready">可继续模拟</option><option value="observe">仅观察</option><option value="blocked">运行阻断</option><option value="invalid">来源不可用</option><option value="expired">已过期</option><option value="critical">严重异常</option><option value="warning">提醒</option><option value="info">进度</option><option value="verified">实验产物已校验</option><option value="cached">实验索引缓存</option></select></label><button id="reset-filters" class="ghost-button">重置</button><small>本地只读 · 不运行策略或发送订单</small></div>
<section id="decisions"><div class="section-head"><h2>决策收件箱</h2><p>按异常、阻断、过期和可模拟状态排序</p></div>{inbox}</section>
<section id="alerts"><div class="section-head"><h2>风险与异常</h2><p>可供调度器或通知系统读取同名 alerts.json</p></div>{alerts}</section>
<section id="accounts"><div class="section-head"><h2>模拟账户汇总</h2><p>按已校验 standard/v2 账户快照汇总</p></div>{accounts}</section>
<section id="current-details"><div class="section-head"><h2>最新决策详情</h2><p>每个目录以 latest.json 为准</p></div>{current}</section>
<section id="experiments"><div class="section-head"><h2>实验与证据</h2><button id="compare-button" class="compare-button" disabled>对比所选实验（0）</button></div><p class="meta">索引仅用于定位运行。存在标准产物时重新校验来源；损坏或缺失的产物不采用缓存指标。</p><p class="meta">{esc(snapshot["index_notice"])}</p>{experiments}</section>
<section id="comparison" hidden><div class="section-head"><h2>所选实验对比</h2></div><p class="notice">逐项并列展示原始指标，不进行收益排名。比较前请核对配置中的观察区间、币种、收益频率与成本假设。</p>{comparisons}</section>
<section id="history"><div class="section-head"><h2>历史记录</h2><p>历史拟调仓不作为当前操作展示</p></div>{"".join(history)}</section></main>
<footer>Quant Report Hub · 研究与模拟用途。账本完整性校验不等于策略投资有效性。看板不修改决策、实验索引或标准产物；证据链接需要原文件留在本机。</footer></div><script>{SCRIPT}</script></body></html>"""


def write_dashboard_bundle(
    roots: list[Path], out: Path, *, db: Path | None = None, now: datetime | None = None
) -> tuple[Path, dict]:
    out = out.resolve()
    roots = [root.resolve() for root in roots]
    # A report cannot overwrite an input pointer, source run, database or the
    # immutable ledger. Publication in each source root is disallowed entirely.
    if out.suffix.lower() != ".html" or any(out.is_relative_to(root) for root in roots):
        raise ValueError("Dashboard output must be an HTML file outside decision roots")
    if db and (out == db.resolve() or out.is_relative_to(db.resolve())):
        raise ValueError("Dashboard output cannot overwrite the experiment database")
    snapshot = dashboard_snapshot(roots, db, now)
    for row in snapshot["experiments"]:
        if out.is_relative_to(Path(row["run_path"]).resolve()):
            raise ValueError("Dashboard output cannot overwrite an indexed run")
    content = render_dashboard(snapshot, out)
    out.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=out.parent, suffix=".tmp", delete=False
        ) as stream:
            name = stream.name
            stream.write(content)
        os.replace(name, out)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()
    return out, snapshot


def write_dashboard(
    roots: list[Path], out: Path, *, db: Path | None = None, now: datetime | None = None
) -> Path:
    """Write the HTML dashboard and preserve the historical public return type."""
    return write_dashboard_bundle(roots, out, db=db, now=now)[0]
