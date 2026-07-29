"""Plot context for quant-report-hub."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from quant_report_hub.adapters.base import RunBundle
from quant_report_hub.adapters import get_adapter
from quant_report_hub.config import VizConfig
from quant_report_hub.metrics import net_value_from_pct, spread_cumulative_pnl
from quant_report_hub.pairing import pair_roundtrips


@dataclass
class PlotContext:
    cfg: VizConfig
    adapter: str
    run_id: str
    run_dir: Path
    portfolio: pd.DataFrame
    symbol: pd.DataFrame
    trades: pd.DataFrame
    signals: pd.DataFrame
    rolls: pd.DataFrame
    summary: pd.DataFrame
    out_dir: Path
    extras: dict[str, pd.DataFrame] = field(default_factory=dict)
    roundtrips: pd.DataFrame = field(default_factory=pd.DataFrame)
    spread_pnl: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    @classmethod
    def from_bundle(cls, cfg: VizConfig, bundle: RunBundle) -> PlotContext:
        port = bundle.portfolio
        if not port.empty and "net_value" not in port.columns and "daily_pnl_pct" in port.columns:
            port = port.copy()
            port["net_value"] = net_value_from_pct(port["daily_pnl_pct"])
        sym = bundle.symbol
        trades = bundle.trades
        rt = pair_roundtrips(trades) if not trades.empty else pd.DataFrame()
        pnl = spread_cumulative_pnl(sym) if not sym.empty else pd.Series(dtype=float)
        out = Path(cfg.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        return cls(
            cfg=cfg,
            adapter=bundle.adapter,
            run_id=bundle.run_id,
            run_dir=bundle.run_dir,
            portfolio=port,
            symbol=sym,
            trades=trades,
            signals=bundle.signals,
            rolls=bundle.rolls,
            summary=bundle.summary,
            out_dir=out,
            extras=bundle.extras,
            roundtrips=rt,
            spread_pnl=pnl,
        )

    @classmethod
    def from_run(
        cls,
        cfg: VizConfig,
        run_id: str | None = None,
        *,
        adapter: str | None = None,
        strategy: str = "",
        initial_capital: float = 10000.0,
    ) -> PlotContext:
        rid = run_id or cfg.run_id
        adapter_name = adapter or cfg.adapter
        bundle = get_adapter(adapter_name, strategy=strategy, initial_capital=initial_capital).load(
            cfg.output_root, rid
        )
        return cls.from_bundle(cfg, bundle)


@dataclass
class CompareContext:
    cfg: VizConfig
    runs: list[PlotContext]
    out_dir: Path


__all__ = ["CompareContext", "PlotContext"]
