"""quant_report_hub/metrics.py — 绩效指标（对齐回测框架加法口径）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_report_hub.config import ANNUAL_DAYS, TRADING_DAYS


def net_value_from_pct(daily_pnl_pct: pd.Series) -> pd.Series:
    """净值 = 1 + cumsum(日收益率)，不复利。"""
    r = daily_pnl_pct.fillna(0.0).astype(float)
    return 1.0 + r.cumsum()


def portfolio_nav(port: pd.DataFrame) -> pd.Series:
    """Resolve net-value series from portfolio daily frame."""
    if "net_value" in port.columns:
        return port["net_value"]
    return net_value_from_pct(port["daily_pnl_pct"])


def drawdown_additive(nav: pd.Series) -> pd.Series:
    """加性回撤：nav - cummax(nav)。"""
    peak = nav.cummax()
    return nav - peak


def drawdown_relative(nav: pd.Series) -> pd.Series:
    """相对回撤：1 - nav / cummax(nav)。"""
    peak = nav.cummax().replace(0, np.nan)
    return 1.0 - nav / peak


def active_returns(daily_pnl_pct: pd.Series) -> pd.Series:
    r = daily_pnl_pct.fillna(0.0).astype(float)
    return r[r != 0]


def summarize_returns(daily_pnl_pct: pd.Series) -> dict[str, float | int | None]:
    """对齐 performance.summarize 口径。"""
    r = daily_pnl_pct.fillna(0.0).astype(float)
    cum = r.cumsum()
    n = len(r)
    active = r[r != 0]
    n_active = len(active)
    total_ret = float(cum.iloc[-1]) if n else 0.0
    ann_ret = total_ret / n * TRADING_DAYS if n else 0.0
    std = float(r.std()) if n > 1 else 0.0
    sharpe = (float(r.mean()) / std * np.sqrt(TRADING_DAYS)) if std > 0 else 0.0
    peak = cum.cummax()
    dd = cum - peak
    max_dd = float(dd.min()) if n else 0.0
    calmar: float | None
    if max_dd < 0:
        calmar = round(ann_ret / abs(max_dd), 4)
    else:
        calmar = None
    win = float((active > 0).sum() / n_active) if n_active else 0.0
    return {
        "days": n,
        "active_days": n_active,
        "total_return": round(total_ret, 6),
        "annual_return": round(ann_ret, 6),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 6),
        "calmar": calmar,
        "win_rate": round(win, 4),
    }


def rolling_sharpe(daily_pnl_pct: pd.Series, window: int) -> pd.Series:
    r = daily_pnl_pct.fillna(0.0).astype(float)
    mean = r.rolling(window, min_periods=window).mean()
    std = r.rolling(window, min_periods=window).std()
    return mean / std * np.sqrt(TRADING_DAYS)


def rolling_max_drawdown(nav: pd.Series, window: int) -> pd.Series:
    def _mdd(x: np.ndarray) -> float:
        if x.size == 0:
            return np.nan
        s = pd.Series(x)
        dd = drawdown_additive(s)
        return float(dd.min())

    return nav.rolling(window, min_periods=window).apply(_mdd, raw=True)


def spread_cumulative_pnl(symbol_daily: pd.DataFrame) -> pd.Series:
    if symbol_daily.empty:
        return pd.Series(dtype=float)
    return symbol_daily.groupby("spread")["daily_pnl"].sum().sort_values(ascending=False)


def spread_nav(symbol_daily: pd.DataFrame) -> pd.DataFrame:
    if symbol_daily.empty:
        return pd.DataFrame()
    parts: list[pd.DataFrame] = []
    for spread, grp in symbol_daily.groupby("spread", sort=False):
        g = grp.sort_values("date").copy()
        g["nav"] = net_value_from_pct(g["daily_pnl_pct"])
        g["spread"] = spread
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def product_prefix(spread: str) -> str:
    """从套利对名提取品种前缀，如 A2105&B2102 -> A。"""
    token = str(spread).split("&")[0]
    letters = "".join(ch for ch in token if ch.isalpha())
    return letters.upper() if letters else token[:2]


def monthly_returns(daily_pnl_pct: pd.Series, dates: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"date": pd.to_datetime(dates), "ret": daily_pnl_pct.fillna(0.0)})
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    return df.groupby(["year", "month"], as_index=False)["ret"].sum()


__all__ = [
    "ANNUAL_DAYS",
    "TRADING_DAYS",
    "active_returns",
    "drawdown_additive",
    "drawdown_relative",
    "monthly_returns",
    "net_value_from_pct",
    "product_prefix",
    "rolling_max_drawdown",
    "rolling_sharpe",
    "spread_cumulative_pnl",
    "spread_nav",
    "summarize_returns",
]
