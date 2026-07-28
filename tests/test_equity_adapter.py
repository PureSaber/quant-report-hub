from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_report_hub.adapters.equity import EquityAdapter


def test_equity_adapter_loads_capital_curve(tmp_path: Path):
    run = tmp_path / "demo"
    run.mkdir()
    pd.DataFrame(
        {
            "date": ["2025-01-31", "2025-02-28", "2025-03-31"],
            "ols": [10000, 10200, 10100],
        }
    ).to_csv(run / "capital_curves.csv", index=False)
    pd.DataFrame({"factor": ["pe"], "ic_mean": [0.03]}).to_csv(run / "ic_summary.csv", index=False)

    bundle = EquityAdapter(strategy="ols").load(tmp_path, "demo")
    assert not bundle.portfolio.empty
    assert "net_value" in bundle.portfolio.columns
    assert not bundle.extras["ic_summary"].empty
