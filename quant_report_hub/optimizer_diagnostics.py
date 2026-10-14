"""Render optimizer evidence already covered by immutable study verification."""

import json
from html import escape


def render_optimizer_section(results):
    sections = []
    for result in results:
        summary = result.get("optimizer_summary")
        if not summary:
            continue
        rows = []
        for decision in summary.get("decisions", []):
            diag = decision.get("diagnostics", {})
            execution = diag.get("execution", {})
            values = (
                decision.get("session"),
                decision.get("mode"),
                decision.get("status", diag.get("status", "legacy")),
                diag.get("solver"),
                diag.get("risk_objective"),
                diag.get("annualized_volatility"),
                diag.get("annualized_tracking_error"),
                diag.get("integer_annualized_tracking_error"),
                diag.get("turnover"),
                execution.get("costs"),
                diag.get("total_seconds"),
                diag.get("max_constraint_residual"),
            )
            cells = "".join(
                "<td>" + escape("—" if value is None else str(value)) + "</td>" for value in values
            )
            evidence = {
                "continuous_weights": decision.get("weights"),
                "integer_targets": decision.get("targets"),
                "current_weights": decision.get("current_weights"),
                "diagnostics": diag,
                "failure": decision.get("error"),
                "published": decision.get("published", True),
            }
            rows.append(
                "<tr>"
                + cells
                + "<td><details><summary>权重、约束与版本</summary><pre>"
                + escape(json.dumps(evidence, ensure_ascii=False, indent=2))
                + "</pre></details></td></tr>"
            )
        headers = (
            "调仓日",
            "方法",
            "状态",
            "求解器",
            "风险目标",
            "连续总风险",
            "连续跟踪误差",
            "整数跟踪误差",
            "换手",
            "预估费用",
            "求解秒数",
            "最大残差",
            "完整诊断",
        )
        sections.append(
            "<h3>"
            + escape(result["candidate"]["name"])
            + "</h3><p>失败调仓："
            + str(summary.get("failed_decisions", 0))
            + " / "
            + str(summary.get("decision_count", 0))
            + "</p>"
            + '<div class="scroll"><table><thead><tr>'
            + "".join("<th>" + x + "</th>" for x in headers)
            + "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
            + "<details><summary>成交后实际持仓风险</summary><pre>"
            + escape(
                json.dumps(summary.get("actual_risk_checks", []), ensure_ascii=False, indent=2)
            )
            + "</pre></details>"
            + "<details><summary>成交后实际持仓与费用</summary><pre>"
            + escape(
                json.dumps(
                    {
                        "positions": summary.get("actual_positions", []),
                        "actual_cost_total": summary.get("actual_cost_total"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            + "</pre></details>"
        )
    if not sections:
        return ""
    return (
        "<section><h2>优化器与执行验收</h2><p>连续目标、整手目标和成交后风险分别记录。风险为年化口径；收益预测期限见版本诊断。整手修复不表示整数全局最优。</p>"
        + "".join(sections)
        + "</section>"
    )
