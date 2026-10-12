"""Native measured returns, without legacy additive return inference."""

from pathlib import Path

import pandas as pd
from quant_lab.measurement import read_measured_run

from quant_report_hub.adapters.base import empty_bundle


class StandardAdapter:
    name = "standard"

    def __init__(self, **kwargs):
        pass

    def load(self, output_root, run_id):
        path = Path(output_root) / run_id
        source = read_measured_run(path)
        if source["manifest"].run_id != run_id:
            raise ValueError("requested run identity differs from native source")
        bundle = empty_bundle(self.name, run_id, path)
        returns = source["returns"]
        bundle.portfolio = pd.DataFrame(
            {"date": returns.event_time, "net_return": returns.net_return}
        )
        bundle.measurement = source["measurement"]
        return bundle
