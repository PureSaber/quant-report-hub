"""quant_report_hub/loader.py — 读取回测 output 目录，统一列名。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_PORTFOLIO_RENAME = {
    "日期": "date",
    "策略": "strategy",
    "套利对数": "num_spreads",
    "日盈亏": "daily_pnl",
    "日收益率": "daily_pnl_pct",
    "手续费": "commission",
    "成交笔数": "num_trades",
    "盈利笔数": "win_trades",
    "净值": "net_value",
}

_SYMBOL_RENAME = {
    "日期": "date",
    "套利对": "spread",
    "策略": "strategy",
    "日盈亏": "daily_pnl",
    "日收益率": "daily_pnl_pct",
    "手续费": "commission",
    "成交笔数": "num_trades",
    "盈利笔数": "win_trades",
    "净值": "net_value",
}

_TRADES_RENAME = {
    "实例ID": "instance_id",
    "价差合约": "spread",
    "成交时间": "datetime",
    "交易日": "trading_day",
    "方向": "direction",
    "开平": "offset",
    "成交价": "price",
    "成交量": "volume",
    "手续费": "commission",
}


def _glob_one(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern))
    return matches[0] if matches else None


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def _normalize(df: pd.DataFrame, rename: dict[str, str]) -> pd.DataFrame:
    out = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"])
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"])
    if "trading_day" in out.columns:
        out["trading_day"] = pd.to_datetime(out["trading_day"])
    return out


def run_dir(output_root: str | Path, run_id: str) -> Path:
    path = Path(output_root) / run_id
    if not path.is_dir():
        raise FileNotFoundError(f"run 目录不存在: {path}")
    return path


def load_portfolio(run_path: str | Path) -> pd.DataFrame:
    root = Path(run_path)
    f = _glob_one(root / "daily" / "portfolio", "daily_pnl_portfolio_*.csv")
    if f is None:
        return pd.DataFrame()
    return _normalize(_read_csv(f), _PORTFOLIO_RENAME).sort_values("date")


def load_symbol_daily(run_path: str | Path) -> pd.DataFrame:
    root = Path(run_path)
    f = _glob_one(root / "daily" / "symbol", "daily_pnl_*.csv")
    if f is None:
        return pd.DataFrame()
    return _normalize(_read_csv(f), _SYMBOL_RENAME).sort_values(["date", "spread"])


def load_trades(run_path: str | Path) -> pd.DataFrame:
    root = Path(run_path)
    f = root / "trades" / "trades.csv"
    if not f.is_file():
        return pd.DataFrame()
    return _normalize(_read_csv(f), _TRADES_RENAME).sort_values(["spread", "datetime"])


def load_signals(run_path: str | Path) -> pd.DataFrame:
    root = Path(run_path)
    f = _glob_one(root / "signals", "signals_*.csv")
    if f is None:
        return pd.DataFrame()
    df = _read_csv(f)
    for col in ("action_datetime", "bar_datetime"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    if "tradingday" in df.columns:
        df["tradingday"] = pd.to_datetime(df["tradingday"], errors="coerce")
    return df.sort_values(["symbol", "action_datetime"])


def load_rolls(run_path: str | Path) -> pd.DataFrame:
    root = Path(run_path)
    f = root / "rolls" / "roll_events.csv"
    if not f.is_file():
        return pd.DataFrame()
    df = _read_csv(f)
    if "tradingday" in df.columns:
        df["tradingday"] = pd.to_datetime(df["tradingday"], errors="coerce")
    return df


def load_summary(run_path: str | Path) -> pd.DataFrame:
    root = Path(run_path)
    f = root / "performance" / "summary.csv"
    if not f.is_file():
        return pd.DataFrame()
    return pd.read_csv(f, encoding="utf-8-sig", index_col=0)


def load_run(output_root: str | Path, run_id: str) -> dict[str, pd.DataFrame | str]:
    """加载单个 run 的全部标准表。"""
    rd = run_dir(output_root, run_id)
    return {
        "run_id": run_id,
        "run_dir": str(rd),
        "portfolio": load_portfolio(rd),
        "symbol": load_symbol_daily(rd),
        "trades": load_trades(rd),
        "signals": load_signals(rd),
        "rolls": load_rolls(rd),
        "summary": load_summary(rd),
    }


__all__ = [
    "load_portfolio",
    "load_rolls",
    "load_run",
    "load_signals",
    "load_summary",
    "load_symbol_daily",
    "load_trades",
    "run_dir",
]
