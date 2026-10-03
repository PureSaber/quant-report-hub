"""Self-contained charts and explicit benchmark choices for verified paired studies."""

import json
from html import escape

LABELS = {
    "base": "基础策略",
    "signal": "信号干预",
    "allocation": "分配干预",
    "risk_latch": "风险开关干预",
    "frequency": "调仓频率干预",
    "fees": "成本干预",
    "delay": "信号延迟干预",
    "cash_buffer": "现金缓冲干预",
    "trend_filter": "趋势筛选干预",
    "passive": "被动持有基准",
    "same_risk_constrained": "同风险约束持有基准",
    "cash": "零息现金基准",
}
COLORS = {
    "base": "#243c50",
    "passive": "#198477",
    "same_risk_constrained": "#9b6b31",
    "cash": "#8a96a3",
}
REFERENCES = ("passive", "same_risk_constrained", "cash")

CSS = """
.paired-only>.stats,.paired-only>.toolbar,.paired-only>#decisions,.paired-only>#alerts,.paired-only>#accounts,.paired-only>#current-details,.paired-only>#experiments,.paired-only>#history{display:none}
.paired-controls{display:flex;gap:18px;flex-wrap:wrap;margin:18px 0}.paired-controls label{font-size:13px;display:flex;gap:10px;align-items:center}.paired-controls select{max-width:100%;padding:9px;border:1px solid #cdd8d2;border-radius:6px;background:white}.paired-plots{display:grid;grid-template-columns:1fr 1fr;gap:18px}.paired-plot{width:100%;height:auto;background:#fafcfb;border:1px solid #dfe6e3;border-radius:9px}.paired-legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;margin:12px 0}.paired-legend i{display:inline-block;width:17px;height:3px;margin:0 5px 3px 0}.effect-track{position:relative;height:14px;background:#eef2f3;min-width:140px}.effect-track:before{content:'';position:absolute;height:100%;width:1px;left:50%;background:#9cabb1}.effect-track span{position:absolute;height:100%;background:#247f91}.effect-track .negative{background:#ad6953}.effect-track .residual{background:#7968a5}.paired-summary{display:flex;gap:22px;flex-wrap:wrap;margin:18px 0}.paired-summary b{font-size:23px;display:block}.paired-summary span{color:#5c6d74;font-size:12px}.paired-audit{font-size:12px;overflow-wrap:anywhere}.paired-definition{max-height:360px;overflow:auto}.paired-view[hidden],.paired-reference[hidden]{display:none!important}@media(max-width:900px){.paired-plots{grid-template-columns:1fr}.paired-controls label{align-items:flex-start;flex-direction:column}.paired-controls select{max-width:75vw}}@media print{.paired-controls{display:none}.paired-plots{grid-template-columns:1fr 1fr}}
"""

SCRIPT = """
document.querySelectorAll('[data-paired]').forEach(root => {
  const picker = root.querySelector('[data-paired-view-select]');
  if (picker) {
    const choose = () => root.querySelectorAll('[data-paired-view]').forEach(el => {
      el.hidden = el.dataset.pairedView !== picker.value;
    });
    picker.addEventListener('change', choose); choose();
  }
  root.querySelectorAll('[data-paired-view]').forEach(view => {
    const reference = view.querySelector('[data-reference-select]');
    const changeReference = () => view.querySelectorAll('[data-reference]').forEach(el => {
      el.hidden = el.dataset.reference !== reference.value;
    });
    reference.addEventListener('change', changeReference); changeReference();
    const candidate = view.querySelector('[data-curve-select]');
    const changeCurve = () => {
      view.querySelectorAll('[data-curve]').forEach(el => {
        el.style.display = el.dataset.curve === candidate.value ? '' : 'none';
      });
      view.querySelector('[data-curve-label]').textContent = candidate.selectedOptions[0].text;
    };
    candidate.addEventListener('change', changeCurve); changeCurve();
  });
});
"""


def _table(headers, rows):
    return (
        '<div class="scroll"><table><thead><tr>'
        + "".join(f"<th>{escape(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
        + "</tbody></table></div>"
    )


def _chart(view, field, title):
    curves = view["curves"]
    values = [v for series in curves.values() for v in series[field]]
    low, high = min(values), max(values)
    padding = (high - low) * 0.1 or 0.01
    low, high = low - padding, high + padding
    width, height, left, top = 670, 210, 60, 24
    x = lambda i: left + width * i / view["sessions"]
    y = lambda v: top + height * (high - v) / (high - low)
    html = f'<svg class="paired-plot" viewBox="0 0 760 285" role="img" aria-label="{escape(title)}"><title>{escape(title)}</title>'
    for i in range(5):
        v = low + (high - low) * i / 4
        html += f'<line x1="{left}" x2="{left + width}" y1="{y(v):.2f}" y2="{y(v):.2f}" stroke="#e0e7e5"/><text x="52" y="{y(v) + 4:.2f}" text-anchor="end" fill="#52656d" font-size="11">{v:.1%}</text>'
    for n in (0, view["sessions"] // 2, view["sessions"]):
        anchor = "start" if n == 0 else "end" if n == view["sessions"] else "middle"
        html += f'<text x="{x(n):.2f}" y="257" text-anchor="{anchor}" fill="#52656d" font-size="11">{escape(view["dates"][n])}</text>'
    for boundary in view["boundaries"]:
        html += f'<line x1="{x(boundary):.2f}" x2="{x(boundary):.2f}" y1="24" y2="234" stroke="#9a9" stroke-dasharray="4 4"><title>独立账户分折边界</title></line>'
    for name, data in curves.items():
        points = " ".join(f"{x(i):.2f},{y(v):.2f}" for i, v in enumerate(data[field]))
        flag = "" if name in COLORS else f' data-curve="{escape(name)}"'
        color = COLORS.get(name, "#7d5fb2")
        html += f'<polyline{flag} fill="none" stroke="{color}" stroke-width="2" points="{points}"><title>{escape(LABELS[name])}</title></polyline>'
    return html + "</svg>"


def _decomposition(item, reference):
    effects = item["one_at_a_time_effects"]
    rows = [(LABELS[k], effects[k], False) for k in LABELS if k in effects]
    rows += [("未解释项及交互残差", item["unexplained_and_interaction_residual"], True)]
    scale = max(abs(v) for _, v, _ in rows) or 1
    body = []
    for label, value, residual in rows:
        width = 50 * abs(value) / scale
        left = 50 if value >= 0 else 50 - width
        tone = "residual" if residual else "negative" if value < 0 else "positive"
        bar = f'<div class="effect-track"><span class="{tone}" style="left:{left:.4f}%;width:{width:.4f}%"></span></div>'
        body.append((escape(label), f"{value * 100:+.4f}", bar))
    gap, total = item["return_gap"], sum(effects.values())
    return (
        f'<section class="paired-reference" data-reference="{reference}"><h4>{LABELS[reference]}相对基础策略的收益差</h4><p>基准差额<strong>{gap * 100:+.4f}</strong>个百分点 = 单项效应合计<strong>{total * 100:+.4f}</strong> + 残差<strong>{(gap - total) * 100:+.4f}</strong>。按未舍入数值守恒；显示舍入可能产生末位差。</p>'
        + _table(["单项干预或剩余差异", "收益差/百分点", "相对基础策略的变化"], body)
        + '<p class="meta">每项效应只改变一个已登记维度。残差包含未识别因素和交互，不能单独称为现金机会成本或已识别因果效应。</p></section>'
    )


def _view(view, index):
    metrics = view["metrics"]
    variants = [name for name in LABELS if name in metrics and name not in COLORS]
    options = "".join(f'<option value="{name}">{LABELS[name]}</option>' for name in variants)
    references = "".join(f'<option value="{name}">{LABELS[name]}</option>' for name in REFERENCES)
    legend = "".join(
        f'<span><i style="background:{color}"></i>{LABELS[name]}</span>'
        for name, color in COLORS.items()
    )
    legend += (
        '<span><i style="background:#7d5fb2"></i><span data-curve-label>所选干预</span></span>'
    )
    rows = [
        (
            LABELS[name],
            f"{metrics[name]['net_return']:+.4%}",
            f"{abs(metrics[name]['max_drawdown']):.4%}",
            f"{(metrics[name]['net_return'] - metrics['base']['net_return']) * 100:+.4f}",
        )
        for name in LABELS
        if name in metrics
    ]
    return (
        f'<article class="card paired-view" data-paired-view="{index}"><h3>{escape(view["title"])}</h3><p class="meta">{view["start"]}—{view["end"]} · {view["sessions"]}个共享交易日期 · 净收益、含期初本金的回撤 · 横轴按观测顺序</p><div class="paired-controls"><label>叠加干预曲线<select data-curve-select>{options}</select></label></div><div class="paired-legend">{legend}</div><div class="paired-plots"><div><h4>累计净收益</h4>{_chart(view, "cumulative", "累计净收益曲线")}</div><div><h4>回撤</h4>{_chart(view, "drawdown", "含期初本金的回撤曲线")}</div></div>'
        + _table(["候选或基准", "净收益", "最大回撤幅度", "相对基础策略/百分点"], rows)
        + f'<div class="paired-controls"><label>收益差参考基准<select data-reference-select>{references}</select></label></div>'
        + "".join(_decomposition(view["decompositions"][r], r) for r in REFERENCES)
        + "</article>"
    )


def _definitions(fold, titles):
    plan, recipe = fold["plan"], fold["recipe"]
    base_risk = plan["base"].get("risk", recipe.get("risk", {}))
    base_model = plan["base"].get("risk_model", recipe.get("risk_model"))
    rows = []
    for name in REFERENCES:
        request = plan["benchmarks"][name]
        if name == "cash":
            summary = "不持证券；每日收益为零；不是国债或无风险利率估计。"
        else:
            strategy = request.get("strategy", {})
            if (
                not isinstance(strategy, dict)
                or not {"family", "top_n", "max_weight", "cash_buffer"}.issubset(strategy)
                or "cost_multiplier" not in request
            ):
                rows.append((LABELS[name], "定义不完整；请查看全部尝试中的失败原因及原始定义。"))
                continue
            risk = request.get("risk", recipe.get("risk", {}))
            model = request.get("risk_model", recipe.get("risk_model"))
            risk_text = (
                "无策略风险限制"
                if not risk
                else "与基础策略相同的风险限制"
                if risk == base_risk
                else "风险限制另行定义"
            )
            model_text = (
                "不启用统计风险模型"
                if model is None
                else "沿用基础风险模型"
                if model == base_model
                else "风险模型另行定义"
            )
            family = {
                "buy_hold": "初始建仓后持有",
                "rank": "排序选股",
                "etf_trend": "趋势筛选后排序",
            }.get(strategy["family"], strategy["family"])
            limits = fold.get("execution_limits", {}).get(name, {})
            if limits and all(type(v) in (int, float) for v in limits.values()):
                budget = f"账本执行上限为{limits['max_holdings']}只，单只权重上限{limits['max_position_weight']:.0%}，现金缓冲{limits['cash_buffer']:.0%}"
            else:
                budget = "尚无完整账本执行上限，见该候选的核验记录"
            summary = f"{family}；{budget}；{risk_text}，{model_text}；成本乘数×{request['cost_multiplier']}。实际投入受整手、成本和执行条件影响。"
        rows.append((LABELS[name], escape(summary)))
    html = (
        '<h3>三个基准的实际定义</h3><p class="meta">适用研究：'
        + escape("、".join(titles))
        + "</p>"
        + _table(["基准", "执行定义"], rows)
    )
    definitions = {
        "signal": ("factors", "评分因子及方向"),
        "allocation": ("allocation", "分配配置"),
        "risk_latch": ("risk", "风险限制"),
        "frequency": ("strategy.frequency", "调仓频率"),
        "fees": ("cost_multiplier", "佣金、最低费用、税费及成交滑点乘数"),
        "delay": ("signal_delay", "信号延迟交易日"),
        "cash_buffer": ("strategy.cash_buffer", "现金缓冲比例；其他持仓上限不变"),
        "trend_filter": ("strategy.family", "趋势筛选；etf_trend开启，rank关闭"),
    }
    rows = []
    for name, variant in plan["variants"].items():
        path, label = definitions[name]
        old, new = plan["base"], variant
        for key in path.split("."):
            old = old.get(key) if isinstance(old, dict) else None
            new = new.get(key) if isinstance(new, dict) else None
        if isinstance(old, dict) and isinstance(new, dict):
            keys = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
            old = {k: old.get(k, "移除") for k in keys}
            new = {k: new.get(k, "移除") for k in keys}
        change = json.dumps(old, ensure_ascii=False) + " → " + json.dumps(new, ensure_ascii=False)
        rows.append((LABELS[name], escape(label), escape(change)))
    return (
        html
        + '<details class="details"><summary>查看每项干预实际改变的内容</summary>'
        + _table(["干预", "维度", "基础值→干预值"], rows)
        + "</details>"
    )


def render_paired(snapshot):
    if not snapshot or not snapshot["folds"]:
        return ""
    folds = snapshot["folds"]
    views = [snapshot["combined"]] if snapshot["combined"] else []
    views += [fold["view"] for fold in folds if fold.get("view")]
    options = "".join(
        f'<option value="{i}">{escape(v["title"])}</option>' for i, v in enumerate(views)
    )
    records, definitions = [], []
    for fold in folds:
        status = (
            "通过产物核验"
            if fold["verified"] and fold["available"]
            else "研究未完成"
            if fold["verified"]
            else "来源核验失败"
        )
        attempts = fold["attempts"]
        done = sum(a["status"] == "completed" for a in attempts)
        records.append(
            (
                escape(fold["title"]),
                escape(status),
                f"{done}/{len(attempts)}" if fold["verified"] else "—",
                escape(fold["reason"]),
            )
        )
        if attempts:
            failure_rows = [
                (escape(LABELS[a["name"]]), escape(a["status"]), escape(str(a.get("error", ""))))
                for a in attempts
            ]
            definitions.append(
                f'<details class="details"><summary>{escape(fold["title"])}：全部尝试、基准和干预定义</summary>'
                + _table(["候选", "状态", "原因"], failure_rows)
                + '<pre class="paired-definition">'
                + escape(json.dumps(fold["plan"], ensure_ascii=False, indent=2))
                + "</pre></details>"
            )
        definitions.append(
            f'<p class="paired-audit">{escape(fold["title"])} · 证据SHA-256：{escape(fold["sha256"])}</p>'
        )
    currencies = sorted({f["context"]["currency"] for f in folds if f.get("context")})
    scopes = sorted({f["context"]["scope"] for f in folds if f.get("context")})
    kind = (
        "合成数据 · 仅验证软件"
        if scopes and all(s.startswith("synthetic") for s in scopes)
        else "回顾性模拟 · 保留全部候选"
        if scopes and all(s.startswith("retrospective") for s in scopes)
        else "来源性质见下方"
    )
    html = f'<section id="paired-research" data-paired><div class="section-head"><h2>受控反事实与基准</h2><span class="badge">{kind}</span></div><p class="notice">单项干预解释已有样本中的收益差，不增加独立市场证据，不选择新赢家。被动持有、同风险约束持有和零息现金回答不同问题；具体定义如下。</p>'
    html += (
        '<p class="meta">来源声明：'
        + escape("；".join(scopes) or "不可用")
        + " · 币种："
        + escape("、".join(currencies) or "不可用")
        + "</p>"
    )
    html += _table(["折/研究", "证据状态", "完成/计划非现金运行", "原因"], records)
    defined = {}
    for fold in folds:
        if fold["verified"]:
            definition_id = json.dumps(
                [
                    fold["plan"],
                    fold["recipe"].get("risk"),
                    fold["recipe"].get("risk_model"),
                    {key: fold.get("execution_limits", {}).get(key) for key in REFERENCES},
                ],
                sort_keys=True,
            )
            if definition_id not in defined:
                defined[definition_id] = (fold, [])
            defined[definition_id][1].append(fold["title"])
    html += "".join(_definitions(fold, titles) for fold, titles in defined.values())
    if len(folds) > 1:
        html += '<p class="notice">各折独立账户、重新入场并计费。跨折曲线仅按日期复合各折净收益，不代表持仓连续账户；候选共用市场日期，不能相加为独立样本。</p>'
    if snapshot["aggregation_error"]:
        html += (
            '<p class="notice error" role="alert">整体汇总不可用：'
            + escape(snapshot["aggregation_error"])
            + "</p>"
        )
    if options:
        html += f'<div class="paired-controls"><label>查看区间<select data-paired-view-select>{options}</select></label></div>'
    html += "".join(_view(v, i) for i, v in enumerate(views))
    return (
        html
        + "".join(definitions)
        + '<p class="meta">页面重新核验绑定的计划、执行定义、标准账本及收益矩阵，并重算描述性收益差；原始行情真实性、完整市场规则与策略有效性仍须单独验收。</p></section>'
    )
