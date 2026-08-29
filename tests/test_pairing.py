"""tests/test_pairing.py — round-trip 配对。"""

from __future__ import annotations

import pandas as pd

from quant_report_hub.pairing import pair_roundtrips


def test_pair_long_roundtrip():
    trades = pd.DataFrame(
        [
            {
                "instance_id": "s1",
                "spread": "A&B",
                "datetime": "2020-01-02 09:00",
                "direction": "LONG",
                "offset": "OPEN",
                "price": 100.0,
                "volume": 1,
                "commission": 1.0,
            },
            {
                "instance_id": "s1",
                "spread": "A&B",
                "datetime": "2020-01-02 15:00",
                "direction": "SHORT",
                "offset": "CLOSE",
                "price": 110.0,
                "volume": 1,
                "commission": 1.0,
            },
        ]
    )
    trades["datetime"] = pd.to_datetime(trades["datetime"])
    rt = pair_roundtrips(trades)
    assert len(rt) == 1
    assert rt.iloc[0]["gross_pnl"] == 8.0  # 10 - 2 commission
