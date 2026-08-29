"""quant_report_hub/pairing.py — 将 fill 配对为 round-trip 交易。"""

from __future__ import annotations

import pandas as pd

_OPEN_CLOSE = {
    ("LONG", "OPEN"): ("SHORT", "CLOSE"),
    ("SHORT", "OPEN"): ("LONG", "CLOSE"),
}


def pair_roundtrips(trades: pd.DataFrame) -> pd.DataFrame:
    """按 (instance_id, spread) 栈式配对开平仓。

    返回列：instance_id, spread, direction, open_time, close_time,
            open_price, close_price, volume, commission, gross_pnl, holding_minutes
    """
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "instance_id",
                "spread",
                "direction",
                "open_time",
                "close_time",
                "open_price",
                "close_price",
                "volume",
                "commission",
                "gross_pnl",
                "holding_minutes",
            ]
        )

    rows: list[dict] = []
    for (iid, spread), grp in trades.groupby(["instance_id", "spread"], sort=False):
        pending: dict[tuple[str, str], dict] = {}
        for _, row in grp.sort_values("datetime").iterrows():
            side = (str(row["direction"]).upper(), str(row["offset"]).upper())
            if side[1] == "OPEN":
                pending[side] = {
                    "instance_id": iid,
                    "spread": spread,
                    "direction": side[0],
                    "open_time": row["datetime"],
                    "open_price": float(row["price"]),
                    "volume": int(row["volume"]),
                    "open_commission": float(row["commission"]),
                }
                continue
            open_side = "LONG" if side[0] == "SHORT" else "SHORT"
            key = (open_side, "OPEN")
            if key not in pending:
                continue
            op = pending.pop(key)
            close_comm = float(row["commission"])
            vol = op["volume"]
            if op["direction"] == "LONG":
                gross = (float(row["price"]) - op["open_price"]) * vol
            else:
                gross = (op["open_price"] - float(row["price"])) * vol
            open_time = pd.Timestamp(op["open_time"])
            close_time = pd.Timestamp(row["datetime"])
            holding = max(0.0, (close_time - open_time).total_seconds() / 60.0)
            rows.append(
                {
                    "instance_id": iid,
                    "spread": spread,
                    "direction": op["direction"],
                    "open_time": open_time,
                    "close_time": close_time,
                    "open_price": op["open_price"],
                    "close_price": float(row["price"]),
                    "volume": vol,
                    "commission": op["open_commission"] + close_comm,
                    "gross_pnl": gross - op["open_commission"] - close_comm,
                    "holding_minutes": holding,
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "instance_id",
                "spread",
                "direction",
                "open_time",
                "close_time",
                "open_price",
                "close_price",
                "volume",
                "commission",
                "gross_pnl",
                "holding_minutes",
            ]
        )
    return pd.DataFrame(rows).sort_values("open_time").reset_index(drop=True)


__all__ = ["pair_roundtrips"]
