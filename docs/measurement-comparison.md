# Measured comparisons

Ordinary multi-run comparisons now use `quant.measurement/v1` from the pinned quant-lab
contract layer. The old equity/spread single-run charts and historical metric panels
remain readable. Incomplete or incompatible economic declarations cannot produce a
multi-run chart or baseline-return difference.

```
quant-report compare --adapter standard --output-root outputs --run-ids candidate baseline --out-dir reports/comparison
```

The native adapter verifies immutable `standard/v2`, reads and hashes the exact bytes it
will parse, and checks the measurement's market input/code identity, observed timestamp
grid, currency, and frozen cost/valuation policy hashes. It supports one strategy return
stream per run. There is no silent selection, intersection, resampling or conversion.
The declaration belongs in `metrics.measurement`; actual frozen policies belong in
`config.measurement_policies.{cost,valuation}`. See `measurement-example.json` and
quant-lab's `docs/measurement.md` for the full closed protocol.

The chart path supports decimal `net_simple_time_weighted` returns only. It compounds
returns and includes opening wealth 1 in drawdown, writes a net-wealth chart, relative
drawdown chart and `measurement-comparison.json`, and does not invent annualized metrics
for irregular event observations. Reports include every declaration and preserve whether
the data is synthetic. Unknown/failed sources or any changed economic dimension return
exit code 2 with concrete reasons. Synthetic compatibility is software evidence only.

The dashboard's ordinary comparison selection uses basis keys produced by the same
Python evaluator. A mix of currency, grid, dates, flow, cost, denominator, benchmark,
data nature or frozen market inputs disables the action. Individual historical metrics
remain accessible under **只读来源指标**, including those without a measurement contract.
Read-only study diagnostics show `MEASUREMENT_UNAVAILABLE` instead of computing economic
differences from unknown or incompatible candidates. Specialized paired interventions
keep their existing verified treatment/evidence contract; they do not claim ordinary
same-input comparability when a data revision changes the market input.
