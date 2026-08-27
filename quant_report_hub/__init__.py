"""Quant research output visualization hub."""

from quant_report_hub.attribution import (
    AttributionManifest,
    attribute_standard_run,
    brinson_fachler_attribution,
    factor_attribution,
    holdings_attribution,
)

__version__ = "0.3.0"

__all__ = [
    "AttributionManifest",
    "attribute_standard_run",
    "brinson_fachler_attribution",
    "factor_attribution",
    "holdings_attribution",
]
