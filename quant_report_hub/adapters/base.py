"""Output adapters for different research projects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


@dataclass
class RunBundle:
    adapter: str
    run_id: str
    run_dir: Path
    portfolio: pd.DataFrame
    symbol: pd.DataFrame
    trades: pd.DataFrame
    signals: pd.DataFrame
    rolls: pd.DataFrame
    summary: pd.DataFrame
    extras: dict[str, pd.DataFrame]


class OutputAdapter(Protocol):
    name: str

    def load(self, output_root: str | Path, run_id: str) -> RunBundle: ...


def empty_bundle(adapter: str, run_id: str, run_dir: Path) -> RunBundle:
    empty = pd.DataFrame()
    return RunBundle(
        adapter=adapter,
        run_id=run_id,
        run_dir=run_dir,
        portfolio=empty,
        symbol=empty,
        trades=empty,
        signals=empty,
        rolls=empty,
        summary=empty,
        extras={},
    )
