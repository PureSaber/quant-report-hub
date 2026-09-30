import pandas as pd
import pytest
from quant_data_kit.financial.reconciliation import adjudicate, discrepancies, publish_decision

from quant_report_hub.cli import main
from quant_report_hub.source_reconciliation import resolution_card


def test_resolution_card_retains_rerun_warning_and_rejects_tampering(tmp_path, capsys):
    data = pd.DataFrame(
        [
            {
                "observation_id": s,
                "instrument_id": "A",
                "field": "dividend",
                "effective_at": "2024-01-01T00:00:00Z",
                "available_at": "2024-01-01T00:00:00Z",
                "value": v,
                "unit": "currency",
                "currency": "CNY",
                "basis": "raw",
                "source": s,
                "evidence_id": s,
            }
            for s, v in (("a", "1"), ("b", "2"))
        ]
    )
    case = discrepancies(data, at="2024-01-02T00:00:00Z")[0]
    decision = adjudicate(
        case,
        selected_observation_id="a",
        resolved_at="2024-01-02T00:00:00Z",
        reviewer="test",
        rationale="evidence",
        evidence_uri="synthetic:source",
        prior_snapshot="old",
        dependencies={"factor": ["b"], "report": ["factor"]},
    )
    path = publish_decision(decision, tmp_path / "resolution.json")
    assert resolution_card(path)["requires_rerun"] == ["factor", "report"]
    assert main(["source-resolution", "--decision", str(path)]) == 0
    assert "resolved_rerun_not_yet_verified" in capsys.readouterr().out
    path.write_text(path.read_text().replace('"reviewer":"test"', '"reviewer":"forged"'))
    with pytest.raises(ValueError, match="hash"):
        resolution_card(path)
