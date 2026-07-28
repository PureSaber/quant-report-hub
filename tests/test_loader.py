"""tests/test_loader.py ? loader ??????"""
from __future__ import annotations

from pathlib import Path

import pytest

from quant_report_hub.loader import load_portfolio, load_run, run_dir

OUTPUT_ROOT = Path(r"d:/temp_framework/ver2/future_spread_analysis-team-framework/output")
RUN_ID = "baseline_dev"


@pytest.mark.skipif(not run_dir(OUTPUT_ROOT, RUN_ID).is_dir(), reason="? baseline_dev ??")
def test_load_portfolio_columns():
    port = load_portfolio(run_dir(OUTPUT_ROOT, RUN_ID))
    assert not port.empty
    assert "date" in port.columns
    assert "daily_pnl_pct" in port.columns


@pytest.mark.skipif(not run_dir(OUTPUT_ROOT, RUN_ID).is_dir(), reason="? baseline_dev ??")
def test_load_run_bundle():
    data = load_run(OUTPUT_ROOT, RUN_ID)
    assert data["run_id"] == RUN_ID
    assert not data["portfolio"].empty
