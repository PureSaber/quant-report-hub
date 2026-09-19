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
    "quantity": "数量",
    "weight": "权重",
    "order_id": "订单编号",
    "side": "方向",
    "reference_close": "参考收盘",
    "estimated_execution_price": "预计成交价",
    "estimated_fee": "预计费用",
    "estimated_slippage": "预计滑点",
    "market_value": "市值",
}


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
        if key == "weight":
            return number(value, percent=True)
        if key == "quantity" and isinstance(value, (float, int)):
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
        ("standard/v2/fills.parquet", "成交"),
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


def decision_panel(item: dict, out: Path) -> str:
    card = item["card"]
    status = item["status"]
    current = item["latest"]
    title = Path(item["root"]).name
    eligible = current and status == "paper_ready"
    deadline = card.get("valid_until") or ""
    expirable = status in {"paper_ready", "observe", "expired"}
    parts = [
        f'''<article class="card" data-search="{esc(title + " " + item["run_id"])}" data-status="{esc(status)}"
      data-latest="{str(current).lower()}" data-valid-until="{esc(deadline)}" data-expirable="{str(expirable).lower()}" data-eligible="{str(eligible).lower()}">
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
        stats = validation.get("net_performance", {})
        stats = stats if isinstance(stats, dict) else {}
        parts.append(
            '<div class="metrics">'
            + "".join(
                f"<div><span>{label}</span><b>{value}</b></div>"
                for label, value in (
                    ("模拟累计收益", number(stats.get("total_return"), percent=True)),
                    ("模拟最大回撤", number(stats.get("max_drawdown"), percent=True)),
                    ("前向观察天数", number(validation.get("forward_observation_days"))),
                    ("行情证券数", number(card["data_quality"].get("symbols"))),
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
            cost = card["estimated_cost"]
            parts.append(
                f'<p class="meta">预计费用 {number(cost.get("fees"))} + 预计滑点 {number(cost.get("slippage"))} = {number(cost.get("total"))} {esc(cost.get("currency", ""))}（来源估计值）</p>'
            )
            parts.append(detail("目标模拟持仓", card["targets"]) + "</section>")
        else:
            parts.append('<p class="muted">本页不展示可操作的拟调仓；历史记录保留供复盘。</p>')
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
    history = []
    for source in sources:
        history.append(
            f'<details class="history"><summary>{esc(Path(source["root"]).name)} · {len(source["history"])} 条历史记录（最多展示 200 条）</summary>'
            + "".join(decision_panel(item, out) for item in source["history"])
            + "</details>"
        )
    experiments, comparisons = experiment_panels(snapshot["experiments"], out)
    bad = sum(source["current"]["status"] in {"invalid", "blocked"} for source in sources)
    cards = (
        (len(sources), "已连接决策目录"),
        ("—", "当前可继续模拟", "ready-count"),
        (bad, "需处理的最新运行"),
        (len(snapshot["experiments"]), "已载入实验 · 最多 200"),
    )
    stats = "".join(
        f'<div class="stat"><strong id="{c[2] if len(c) == 3 else "stat-" + str(i)}">{c[0]}</strong><span>{c[1]}</span></div>'
        for i, c in enumerate(cards)
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Quant Report Hub · 研究看板</title><style>{CSS}</style></head>
<body><div class="shell"><header><div class="brand"><b>Q</b>quant-report-hub</div><nav aria-label="主导航"><a href="#decisions">决策概览</a><a href="#experiments">实验与对比</a><a href="#history">历史记录</a></nav></header>
<main><section class="hero"><div><p class="eyebrow">RESEARCH / PAPER / EVIDENCE</p><h1>每次决策，都有据可查。</h1><p class="intro">把数据状态、模拟决策与研究证据放在一起。先确认来源与时效，再查看结果。</p></div><div class="meta">看板快照生成于<br>{esc(snapshot["generated_at"])}<br>来源更新后，请重新生成本页。</div></section>
<div class="stats">{stats}</div><noscript><p class="notice warning">启用 JavaScript 后可筛选、对比及检查实时有效期。拟调仓默认隐藏；其他来源信息仍可阅读。</p></noscript>
<div class="toolbar"><label>搜索 <input id="search" type="search" placeholder="项目、目录或运行编号"></label><label>状态 <select id="status-filter"><option value="all">全部状态</option><option value="paper_ready">可继续模拟</option><option value="observe">仅观察</option><option value="blocked">运行阻断</option><option value="invalid">来源不可用</option><option value="expired">已过期</option><option value="verified">实验产物已校验</option><option value="cached">实验索引缓存</option></select></label><small>本地只读 · 不运行策略或发送订单</small></div>
<section id="decisions"><div class="section-head"><h2>最新决策</h2><p>每个目录以 latest.json 为准</p></div>{current}</section>
<section id="experiments"><div class="section-head"><h2>实验与证据</h2><button id="compare-button" class="compare-button" disabled>对比所选实验（0）</button></div><p class="meta">索引仅用于定位运行。存在标准产物时重新校验来源；损坏或缺失的产物不采用缓存指标。</p><p class="meta">{esc(snapshot["index_notice"])}</p>{experiments}</section>
<section id="comparison" hidden><div class="section-head"><h2>所选实验对比</h2></div><p class="notice">逐项并列展示原始指标，不进行收益排名。比较前请核对配置中的观察区间、币种、收益频率与成本假设。</p>{comparisons}</section>
<section id="history"><div class="section-head"><h2>历史记录</h2><p>历史拟调仓不作为当前操作展示</p></div>{"".join(history)}</section></main>
<footer>Quant Report Hub · 研究与模拟用途。账本完整性校验不等于策略投资有效性。看板不修改决策、实验索引或标准产物；证据链接需要原文件留在本机。</footer></div><script>{SCRIPT}</script></body></html>"""


def write_dashboard(
    roots: list[Path], out: Path, *, db: Path | None = None, now: datetime | None = None
) -> Path:
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
    return out
