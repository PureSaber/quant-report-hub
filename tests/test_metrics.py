"""tests/test_metrics.py — 指标口径。"""
from __future__ import annotations

import pandas as pd

from quant_report_hub.metrics import drawdown_additive, net_value_from_pct, summarize_returns


def test_additive_nav():
    r = pd.Series([0.1, 0.05, -0.08, 0.02])
    nav = net_value_from_pct(r)
    assert abs(nav.iloc[-1] - 1.09) < 1e-9


def test_summarize_matches_framework_additive_dd():
    r = pd.Series([0.1, 0.05, -0.08, 0.02])
    s = summarize_returns(r)
    cum = r.cumsum()
    assert abs(s["max_drawdown"] - float((cum - cum.cummax()).min())) < 1e-9


def test_drawdown_additive():
    nav = net_value_from_pct(pd.Series([0.01, -0.02, 0.01]))
    dd = drawdown_additive(nav)
    assert dd.max() <= 0
