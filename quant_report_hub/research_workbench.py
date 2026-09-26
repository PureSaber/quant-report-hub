"""Read-only study comparison and evidence-backed robustness diagnostics."""

from __future__ import annotations

import argparse
import json
import sqlite3
from html import escape
from pathlib import Path

from quant_lab.research import canonical, compare_results, digest, verify_result


def load_study(path: Path) -> dict:
    summary = json.loads(path.read_text(encoding="utf-8"))
    if summary.get("schema_version") != "quant.research-study/v1":
        raise ValueError("Unsupported research study schema")
    with sqlite3.connect(
        (path.parent / "experiments.db").resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        row = db.execute(
            "SELECT definition,sha256 FROM studies WHERE study_id=?", (summary["study_id"],)
        ).fetchone()
        events = db.execute(
            "SELECT attempt_id,status,payload FROM trial_events WHERE study_id=? ORDER BY sequence",
            (summary["study_id"],),
        ).fetchall()
    if (
        row is None
        or digest(json.loads(row[0])) != row[1]
        or row[1] != summary["definition_sha256"]
    ):
        raise ValueError("Study definition differs from registry")
    definition = json.loads(row[0])
    if definition["recipe"] != summary["recipe"]:
        raise ValueError("Recipe differs from preregistration")
    expected = {r["candidate_id"]: r for r in definition["parameters"]}
    actual = [r["candidate"]["candidate_id"] for r in summary["results"]]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError("Summary omits or duplicates preregistered candidates")
    if any(r["candidate"] != expected[r["candidate"]["candidate_id"]] for r in summary["results"]):
        raise ValueError("Candidate differs from preregistration")
    if any(
        summary[field] != sum(r["status"] == status for r in summary["results"])
        for field, status in (("completed", "completed"), ("failed", "failed"))
    ):
        raise ValueError("Study result counts differ from candidates")
    terminals = {
        attempt: (status, json.loads(payload))
        for attempt, status, payload in events
        if status != "running"
    }
    for result in summary["results"]:
        terminal = terminals.get(result["attempt_id"])
        if terminal is None or terminal[0] != result["status"]:
            raise ValueError("Study result missing from attempt registry")
        if result["status"] == "completed":
            record = terminal[1]
            artifact = (path.parent / record["result"]).resolve()
            if path.parent.resolve() not in artifact.parents:
                raise ValueError("Result path escapes study")
            actual = verify_result(artifact, record["sha256"])
            if actual != result:
                raise ValueError("Summary differs from immutable candidate result")
        elif terminal[1] != result:
            raise ValueError("Failure summary differs from attempt registry")
    return summary


def diagnose(summary: dict) -> list[dict]:
    rows = {r["candidate"]["name"]: r for r in summary["results"] if r["status"] == "completed"}
    findings = []
    base = rows.get("base")
    if base is None:
        return [
            {
                "code": "BASELINE_UNAVAILABLE",
                "message": "主实验未完成，无法判断策略表现。",
                "evidence": [],
            }
        ]
    if base["scope"].startswith("fixture"):
        return [
            {
                "code": "FIXTURE_ONLY",
                "message": "这是固定样例的软件验证，收益不能作为投资表现。",
                "evidence": ["base"],
            }
        ]
    if base["scope"].startswith("synthetic"):
        findings.append(
            {
                "code": "SYNTHETIC_ONLY",
                "message": "以下结果使用合成行情，仅验证软件流程，不能作为投资表现。",
                "evidence": ["base"],
            }
        )
    baseline = rows.get("buy_hold")
    if baseline and compare_results([base, baseline])["comparable"]:
        difference = base["metrics"]["total_return"] - baseline["metrics"]["total_return"]
        findings.append(
            {
                "code": "NET_BASELINE_DIFFERENCE",
                "message": f"主实验相对同仓位买入持有的净收益差为{difference:.2%}。",
                "value": difference,
                "evidence": ["base", "buy_hold"],
            }
        )
    for name, result in rows.items():
        if name == "base" or name == "buy_hold":
            continue
        difference = result["metrics"]["total_return"] - base["metrics"]["total_return"]
        findings.append(
            {
                "code": "PAIRED_PERTURBATION",
                "message": f"{name}相对主实验的净收益变化为{difference:.2%}。",
                "value": difference,
                "evidence": ["base", name],
                "interpretation": "预先登记的配对诊断；不自动选取收益最高的候选",
            }
        )
    for row in base.get("factor_evidence", {}).get("correlations", []):
        correlation = row["rank_correlation"]
        if correlation is not None and abs(correlation) >= 0.9:
            findings.append(
                {
                    "code": "FACTOR_REDUNDANCY",
                    "message": f"{row['left']}与{row['right']}的平均截面秩相关为{correlation:.3f}。",
                    "evidence": ["base/factors.json"],
                }
            )
    windows = [s for s in base.get("segments", []) if "window" in s]
    if windows:
        positives = sum(s["net_return"] > 0 for s in windows)
        findings.append(
            {
                "code": "SUBPERIOD_STABILITY",
                "message": f"{len(windows)}个连续子区间中{positives}个净收益为正；区间长短可能不同。",
                "evidence": ["base/returns.csv"],
            }
        )
    if summary["failed"]:
        findings.append(
            {
                "code": "INCOMPLETE_STUDY",
                "message": "部分候选失败，不能只凭成功候选评价整个研究。",
                "evidence": [
                    r["candidate"]["name"] for r in summary["results"] if r["status"] != "completed"
                ],
            }
        )
    return findings


def _metric(value, percent=False):
    if value is None:
        return "—"
    return f"{value:.2%}" if percent else f"{value:.4g}"


def render_study(source: Path, output: Path) -> dict:
    summary = load_study(source)
    findings = diagnose(summary)
    comparison = compare_results(summary["results"])
    root = source.parent.resolve()
    target = output.resolve()
    if (
        target.suffix.lower() != ".html"
        or target == source.resolve()
        or (root / "attempts") in target.parents
    ):
        raise ValueError("Report output cannot overwrite study or candidate artifacts")
    rows = []
    for result in summary["results"]:
        candidate = result["candidate"]
        metrics = result.get("metrics", {})
        row = [
            candidate["name"],
            result["status"],
            _metric(metrics.get("total_return"), True),
            _metric(metrics.get("max_drawdown"), True),
            _metric(metrics.get("sharpe")),
            str(metrics.get("fills", "—")),
            _metric(metrics.get("cost_total")),
            result.get("error", ""),
        ]
        rows.append(
            "<tr>" + "".join("<td>" + escape(str(cell)) + "</td>" for cell in row) + "</tr>"
        )
    evidence = {
        "schema_version": "quant.research-diagnostics/v1",
        "study_id": summary["study_id"],
        "findings": findings,
        "comparison": {k: v for k, v in comparison.items() if k != "results"},
    }
    evidence_path = output.with_suffix(".diagnostics.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(canonical(evidence), encoding="utf-8")
    cards = "".join(
        "<li><strong>" + escape(f["code"]) + "</strong> " + escape(f["message"]) + "</li>"
        for f in findings
    )
    limitations = sorted({text for r in summary["results"] for text in r.get("limitations", [])})
    base = next(
        (
            r
            for r in summary["results"]
            if r["candidate"]["name"] == "base" and r["status"] == "completed"
        ),
        {},
    )
    factors = base.get("factor_evidence", {})
    coverage = {r["factor"]: r["coverage"] for r in factors.get("coverage", [])}
    factor_rows = []
    for item in factors.get("ic_decay", []):
        values = [
            item["factor"],
            item["horizon"],
            item["sessions"],
            _metric(coverage.get(item["factor"]), True),
            _metric(item["mean_ic"]),
            _metric(item["rank_ic"]),
            _metric(item["rank_ic_ir"]),
            _metric(item["positive_ratio"], True),
        ]
        factor_rows.append(
            "<tr>" + "".join("<td>" + escape(str(v)) + "</td>" for v in values) + "</tr>"
        )
    factor_html = (
        (
            '<section><h2>因子筛选证据</h2><p class="muted">原始因子方向；只使用已成熟标签。重叠标签下的ICIR是描述指标，不是显著性结论。</p><div class="scroll"><table><thead><tr><th>因子</th><th>持有日</th><th>有效截面</th><th>覆盖率</th><th>IC</th><th>RankIC</th><th>ICIR</th><th>正IC比例</th></tr></thead><tbody>'
            + "".join(factor_rows)
            + "</tbody></table></div><details><summary>分年度、行业、市场状态及冗余</summary><pre>"
            + escape(
                json.dumps(
                    {k: factors.get(k, []) for k in ("segments", "correlations")},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            + "</pre></details></section>"
        )
        if factor_rows
        else ""
    )
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>策略研究 · {escape(summary["study_id"])}</title>
<style>body{{font:15px/1.65 system-ui,sans-serif;background:#f4f6fa;color:#182334;margin:0}}main{{max-width:1240px;margin:auto;padding:32px}}h1{{font-size:30px;margin:0}}.muted{{color:#64748b}}section{{background:white;padding:24px;border:1px solid #dfe5ee;border-radius:12px;margin:20px 0}}.stats{{display:flex;gap:36px}}.stats b{{font-size:28px;display:block}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #e6ebf2}}th{{background:#f1f5fa}}.scroll{{overflow:auto}}input{{padding:10px;border:1px solid #ccd5e1;border-radius:6px;width:280px;max-width:90%}}li{{margin:10px 0}}pre{{white-space:pre-wrap;word-break:break-word;font-size:12px}}details{{margin-top:16px}}.badge{{color:#17605c;background:#e4f4f0;padding:4px 10px;border-radius:20px}}</style>
<main><p class="muted">PURESABER / RESEARCH WORKBENCH</p><h1>{escape(summary["study_id"])}</h1>
<p>{escape(summary["recipe"]["hypothesis"])}</p><span class="badge">{escape(summary["recipe"]["mode"])} · 全部候选留痕</span>
<section class="stats"><div><b>{len(summary["results"])}</b>预登记候选</div><div><b>{summary["completed"]}</b>完成</div><div><b>{summary["failed"]}</b>失败</div><div><b>{len(summary["attempts"])}</b>审计事件</div></section>
<section><h2>实验比较</h2><p class="muted">成本压力实验单独标识口径差异；不按最高收益自动晋级。收益来自模拟账本。</p><input id="filter" placeholder="筛选实验名称或状态" aria-label="筛选实验"><div class="scroll"><table><thead><tr><th>实验</th><th>状态</th><th>净收益</th><th>最大回撤</th><th>Sharpe</th><th>成交</th><th>费用</th><th>失败原因</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>
<section><h2>稳健性与失败诊断</h2><ul>{cards}</ul><p class="muted">诊断反映配对实验结果，不是收益预测或因果证明。未触碰留出区间须单独等待并评估。</p></section>
<section><h2>证据与适用范围</h2><ul>{"".join("<li>" + escape(s) + "</li>" for s in limitations)}</ul><details><summary>比较口径差异</summary><pre>{escape(json.dumps(comparison["mismatches"], ensure_ascii=False, indent=2))}</pre></details><details><summary>冻结研究配方</summary><pre>{escape(json.dumps(summary["recipe"], ensure_ascii=False, indent=2))}</pre></details></section>
{factor_html}</main><script>document.getElementById('filter').addEventListener('input',function(){{const q=this.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));}});</script></html>"""
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render_study(args.study, args.output)


if __name__ == "__main__":
    main()
