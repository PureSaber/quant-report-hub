"""Spread backtest output adapter (future_spread_analysis)."""

from __future__ import annotations

from pathlib import Path

from quant_report_hub.adapters.base import RunBundle
from quant_report_hub.loader import load_run, run_dir


class SpreadAdapter:
    name = "spread"

    def load(self, output_root: str | Path, run_id: str) -> RunBundle:
        rd = run_dir(output_root, run_id)
        data = load_run(output_root, run_id)
        return RunBundle(
            adapter=self.name,
            run_id=run_id,
            run_dir=rd,
            portfolio=data["portfolio"],
            symbol=data["symbol"],
            trades=data["trades"],
            signals=data["signals"],
            rolls=data["rolls"],
            summary=data["summary"],
            extras={},
        )


def get_spread_adapter() -> SpreadAdapter:
    return SpreadAdapter()
