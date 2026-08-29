from __future__ import annotations

import json
from pathlib import Path

from scripts.check_coverage import main as check_coverage

ROOT = Path(__file__).resolve().parents[1]
QUANT_LAB_COMMIT = "27489d270e132adbec1bced93eb2ae84ad5e1a9b"


def test_metadata_declares_reporting_contracts_and_lock_file():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.4.1"' in metadata
    assert 'layer = "reporting"' in metadata
    assert '{ id = "standard/v2", version = "2.0.0", direction = "consumes" }' in metadata
    assert (
        '{ id = "puresaber.run-manifest", version = "2.0.0", direction = "consumes" }' in metadata
    )
    assert (
        '{ id = "quant-report-hub.attribution-report", version = "2.0", direction = "produces" }'
        in metadata
    )
    assert 'lock-files = ["requirements.lock"]' in metadata


def test_quant_lab_release_tag_and_lock_are_immutable():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert "quant-lab.git@v0.3.1" in metadata
    assert f"quant-lab.git@{QUANT_LAB_COMMIT}" in lock
    assert "annotated tag v0.3.1" in lock
    assert "quant-lab.git@main" not in metadata + lock
    assert "quant-lab.git@master" not in metadata + lock


def test_coverage_gate_normalizes_windows_paths(tmp_path: Path):
    report_path = tmp_path / "coverage.json"
    report_path.write_text(
        json.dumps(
            {
                "totals": {"percent_covered": 80.0},
                "files": {
                    "quant_report_hub\\attribution.py": {
                        "summary": {"num_branches": 10, "covered_branches": 9}
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert check_coverage(["check_coverage.py", str(report_path)]) == 0
