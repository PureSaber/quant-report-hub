"""Render integrity evidence separately from profitability and live-trading approval."""

import argparse
import json
from html import escape
from pathlib import Path

from quant_lab.research import file_hash

WARNINGS = {
    "quant.family-evidence/v1": [
        "DSR depends on the complete trial family and the effective-trial assumption; annualized Sharpe is display-only.",
        "CSCV/PBO is not chronological OOS validation; purged combinations are a separate estimand.",
        "SPA rejects a joint null, not proves the chosen strategy; MCS may include all candidates.",
        "Report every block-length sensitivity. Failure or missing evidence is not a statistical pass.",
    ],
    "quant.paired-evidence/v1": [
        "Effects are one-at-a-time simulated return changes, not causal estimates.",
        "Passive, same-risk-constrained and zero-interest cash benchmarks answer different questions.",
        "The residual reconciles the gap but is not an identified interaction effect.",
    ],
}


def _family_inventory(audit):
    """Expose the collector's full inventory without hiding failures in raw JSON."""
    reasons = {
        row["candidate"]: row for row in audit.get("unavailable_reasons", []) if "candidate" in row
    }
    errors = {row["attempt_id"]: row["reason"] for row in audit.get("collection_errors", [])}
    names = {}
    for study in audit.get("inventory", {}).get("studies", []):
        for event in study.get("events", []):
            if event["status"] == "running":
                parameters = event["payload"]["parameters"]
                names[event["attempt_id"]] = (
                    study["study_id"] + " / " + str(parameters.get("name", parameters))
                )
        for attempt in study.get("attempts", []):
            if attempt["status"] != "completed":
                payload = attempt["payload"]
                errors[attempt["attempt_id"]] = payload.get("error", payload.get("reason", ""))
    rows = []
    for key in audit.get("planned", []):
        reason = reasons.get(key, {})
        missing = reason.get("missing")
        cells = (
            names.get(key, key),
            key,
            audit["statuses"][key],
            "缺失" if missing is True else "见核验记录",
            errors.get(key, "未完成或未登记" if audit["statuses"][key] != "completed" else ""),
        )
        rows.append("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in cells) + "</tr>")
    problems = [*audit.get("unavailable_reasons", []), *audit.get("collection_errors", [])]
    html = "<section><h2>完整尝试与缺失记录</h2><p>保留失败、中断、重试及尚未登记的成员；不能只展示成功结果。</p>"
    if rows:
        html += (
            '<div class="scroll"><table><tr><th>研究 / 候选</th><th>尝试或占位标识</th>'
            "<th>状态</th><th>收益序列</th><th>失败或缺失原因</th></tr>"
            + "".join(rows)
            + "</table></div>"
        )
    else:
        html += "<p>此快照未提供逐项清单。</p>"
    if problems:
        html += (
            "<h3>统计不可用的核验原因</h3><pre>"
            + escape(json.dumps(problems, ensure_ascii=False, indent=2))
            + "</pre>"
        )
    return html + "</section>"


def render_evidence(source: Path, output: Path, *, expected_sha256: str):
    if file_hash(source) != expected_sha256:
        raise ValueError("evidence snapshot hash mismatch")
    value = json.loads(source.read_text(encoding="utf-8"))
    schema = value.get("schema")
    if schema not in WARNINGS:
        raise ValueError("unsupported research evidence schema")
    if output.suffix.lower() != ".html" or output.resolve() == source.resolve():
        raise ValueError("separate HTML output required")
    cards = []
    family_html = ""
    if schema == "quant.family-evidence/v1":
        audit = value["audit"]
        if not audit["available"] and any(
            method.get("available") is True for method in value.get("methods", {}).values()
        ):
            raise ValueError("unavailable family cannot expose available statistical methods")
        family_html = (
            '<section aria-label="家族统计可用性"><h2>家族统计可用性</h2><p>'
            + (
                "完整性核验通过；各统计方法是否可用及其解释边界仍需分别查看。"
                if audit["available"]
                else "家族统计结论不可用；失败或缺失成员不能从候选族中删除。"
            )
            + "</p></section>"
            + _family_inventory(audit)
        )
        cards.append(("Family availability", audit.get("available")))
        for name in ("dsr", "cscv", "spa_mcs", "bootstrap"):
            method = value.get("methods", {}).get(name)
            status = (
                "not requested / unavailable"
                if method is None
                else (
                    "available (not an investment approval)"
                    if method["available"]
                    else method.get("reason", "unavailable")
                )
            )
            cards.append((name, status))
        title = "研究家族：选择偏差与依赖性"
    else:
        cards.append(("Attribution availability", value["available"]))
        for key, effect in value.get("attribution", {}).get("one_at_a_time_effects", {}).items():
            cards.append((key, effect))
        title = "收益差额：受控配对实验"
    html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    html += "<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:40px auto;padding:20px;color:#172534}td,th{padding:12px;border-bottom:1px solid #ccd;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}table{width:100%}.scroll{overflow:auto}section{padding:18px;background:#f4f6fa;margin:20px 0;border-radius:10px}</style>"
    html += f"<title>{title}</title><h1>{title}</h1><p>核验输入快照 SHA-256：{escape(expected_sha256)}。未重新运行统计检验或证明原始数据真实。</p>"
    html += family_html + "<table><tr><th>证据</th><th>状态 / 数值</th></tr>"
    html += "".join(
        f"<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>" for k, v in cards
    )
    html += (
        "</table><h2>解释边界</h2><ul>"
        + "".join(f"<li>{escape(v)}</li>" for v in WARNINGS[schema])
        + "</ul>"
    )
    html += "<p>研究结果不构成投资建议，不自动放宽风险约束或授权交易。</p><details><summary>完整可审查证据（包括失败、缺失与敏感性）</summary><pre>"
    html += escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre></details></html>"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return {"schema": schema, "input_sha256": expected_sha256, "cards": cards}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    render_evidence(args.source, args.output, expected_sha256=args.sha256)


if __name__ == "__main__":
    main()
