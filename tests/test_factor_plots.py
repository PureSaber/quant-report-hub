from pathlib import Path

import pandas as pd

from quant_report_hub.adapters.equity import EquityAdapter
from quant_report_hub.config import VizConfig
from quant_report_hub.context import PlotContext
from quant_report_hub.plots.registry import PLOT_REGISTRY, run_plots


def test_factor_ic_bar_and_quantile_spread_registered():
    assert "18" in PLOT_REGISTRY
    assert "19" in PLOT_REGISTRY


def test_factor_plots_render(tmp_path: Path):
    run = tmp_path / "demo"
    run.mkdir()
    pd.DataFrame(
        {
            "date": ["2025-01-31", "2025-02-28", "2025-03-31"],
            "q5": [10000, 10200, 10100],
            "q1": [9800, 9900, 9700],
        }
    ).to_csv(run / "capital_curves.csv", index=False)
    pd.DataFrame({"factor": ["momentum_20d"], "ic_mean": [0.04]}).to_csv(
        run / "ic_summary.csv", index=False
    )

    bundle = EquityAdapter(strategy="q5").load(tmp_path, "demo")
    out_dir = tmp_path / "plots"
    cfg = VizConfig(output_root=str(tmp_path), run_id="demo", out_dir=str(out_dir), adapter="equity")
    ctx = PlotContext.from_bundle(cfg, bundle)
    outputs = run_plots(ctx, ("18", "19"))
    assert any(p.name.endswith("16_ic_summary.png") for p in outputs)
    assert any(p.name.endswith("19_quantile_spread.png") for p in outputs)
