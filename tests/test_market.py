"""tests/test_market.py — 行情路径解析。"""
from __future__ import annotations

from pathlib import Path

import pytest

from quant_report_hub.market import load_spread_bars, spread_pair_folder

MARKET_ROOT = Path(r"D:/data/跨品种")


@pytest.mark.skipif(not MARKET_ROOT.is_dir(), reason="无本地行情目录")
def test_spread_pair_folder():
    assert spread_pair_folder("A2105&B2102") == "A&B"


@pytest.mark.skipif(not MARKET_ROOT.is_dir(), reason="无本地行情目录")
def test_load_spread_bars_marketdata_layout():
    bars = load_spread_bars(MARKET_ROOT, "A2105&B2102", ["2020"])
    assert not bars.empty
    assert "close" in bars.columns
