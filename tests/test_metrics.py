"""tests/test_metrics.py — 指标口径。"""

from __future__ import annotations

import pandas as pd
import pytest

from quant_report_hub.metrics import (
    drawdown_additive,
    drawdown_relative,
    net_value_from_pct,
    rolling_max_drawdown,
    summarize_returns,
)


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


@pytest.mark.parametrize(
    "returns, expected", [([-0.1, 0.05], -0.1), ([-0.1], -0.1), ([0.1, 0.05], 0.0), ([], 0.0)]
)
def test_drawdown_includes_initial_capital(returns, expected):
    series = pd.Series(returns, dtype=float)
    assert summarize_returns(series)["max_drawdown"] == pytest.approx(expected)
    if returns:
        nav = net_value_from_pct(series)
        assert drawdown_additive(nav).min() == pytest.approx(expected)
        assert drawdown_relative(nav).max() == pytest.approx(-expected)


def test_rolling_window_does_not_inherit_full_history_initial_nav():
    assert rolling_max_drawdown(pd.Series([0.8, 0.85, 0.9]), 2).iloc[-1] == 0.0
