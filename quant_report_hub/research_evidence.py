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
    if schema == "quant.family-evidence/v1":
        audit = value["audit"]
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
    html += "<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:40px auto;padding:20px;color:#172534}td,th{padding:12px;border-bottom:1px solid #ccd}pre{white-space:pre-wrap;overflow-wrap:anywhere}table{width:100%}</style>"
    html += f"<title>{title}</title><h1>{title}</h1><p>核验输入快照 SHA-256：{escape(expected_sha256)}。未重新运行统计检验或证明原始数据真实。</p><table><tr><th>证据</th><th>状态 / 数值</th></tr>"
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
