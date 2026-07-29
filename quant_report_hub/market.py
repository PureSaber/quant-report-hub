"""quant_report_hub/market.py — 读取外部价差行情 CSV。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def spread_product(spread: str) -> str:
    token = str(spread).split("&")[0]
    letters = "".join(ch for ch in token if ch.isalpha())
    return letters.lower() if letters else token[:1].lower()


def spread_pair_folder(spread: str) -> str:
    """A2105&B2102 -> A&B。"""
    parts = str(spread).split("&")
    if len(parts) < 2:
        return spread
    p0 = "".join(ch for ch in parts[0] if ch.isalpha()).upper()
    p1 = "".join(ch for ch in parts[1] if ch.isalpha()).upper()
    return f"{p0}&{p1}"


def _resolve_roots(market_root: str | Path) -> list[Path]:
    root = Path(market_root)
    roots = [root]
    md = root / "MarketData"
    if md.is_dir():
        roots.insert(0, md)
    return roots


def _spread_path_candidates(roots: list[Path], year: str, spread: str) -> list[Path]:
    product = spread_product(spread)
    pair = spread_pair_folder(spread)
    paths: list[Path] = []
    for root in roots:
        paths.extend([
            root / year / product / product / f"{spread}.csv",
            root / year / product / f"{spread}.csv",
            root / year / pair / f"{spread}.csv",
        ])
    # 去重保序
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def load_spread_bars(
    market_root: str | Path,
    spread: str,
    years: list[str],
) -> pd.DataFrame:
    """加载 comb 收盘价序列；列至少含 datetime, close。"""
    roots = _resolve_roots(market_root)
    frames: list[pd.DataFrame] = []
    for year in years:
        found = False
        for path in _spread_path_candidates(roots, str(year), spread):
            if not path.is_file():
                continue
            frames.append(pd.read_csv(path, encoding="utf-8-sig"))
            found = True
            break
        if not found:
            continue
    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"])
        out = out.sort_values("datetime")
    close_col = "close_price" if "close_price" in out.columns else "close"
    if close_col not in out.columns:
        return pd.DataFrame()
    out["close"] = pd.to_numeric(out[close_col], errors="coerce")
    out = out.dropna(subset=["close"])
    return out.reset_index(drop=True)


def compute_zscore(closes: pd.Series, lookback: int) -> pd.Series:
    """滚动 z-score，窗口不足时为 NaN。"""
    s = closes.astype(float)
    mu = s.rolling(lookback, min_periods=lookback).mean()
    std = s.rolling(lookback, min_periods=lookback).std()
    return (s - mu) / std.replace(0, pd.NA)


__all__ = ["compute_zscore", "load_spread_bars", "spread_pair_folder", "spread_product"]
