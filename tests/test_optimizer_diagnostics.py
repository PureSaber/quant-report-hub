from quant_report_hub.optimizer_diagnostics import render_optimizer_section


def test_optimizer_report_preserves_failure_and_escapes_values():
    result = {
        "candidate": {"name": "<script>bad()</script>"},
        "optimizer_summary": {
            "decision_count": 1,
            "failed_decisions": 1,
            "decisions": [
                {
                    "session": "2026-01-01",
                    "status": "repair_failed",
                    "published": False,
                    "error": "<img src=x>",
                    "diagnostics": {"versions": {"cvxpy": "1.7.5"}},
                }
            ],
            "actual_risk_checks": [{"stage": "realized"}],
        },
    }
    html = render_optimizer_section([result])
    assert "repair_failed" in html and "1.7.5" in html and "realized" in html
    assert "<script>bad" not in html and "<img src=x>" not in html
    assert "&lt;script&gt;" in html
    assert render_optimizer_section([{}]) == ""
