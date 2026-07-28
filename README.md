# quant-report-hub

Unified visualization hub refactored from [spread-backtest-viz](../spread-backtest-viz). The original `spread-backtest-viz` repo is **not modified**; this project adds adapter-based support for equity research outputs.

## Install

```bash
cd quant-report-hub
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Adapters

| Adapter | Source projects | Output layout |
|---------|-----------------|---------------|
| `spread` | future_spread_analysis | `output/<run_id>/daily/portfolio/...` |
| `equity` | a-share-multifactor, sklearn-stock-trend | `outputs/<run_id>/capital_curves.csv` |

## Usage

### Futures spread (same as spread-backtest-viz)

```bash
quant-report run ^
  --adapter spread ^
  --output-root "D:/projects/future_spread_analysis-team-framework/output" ^
  --run-id baseline_dev ^
  --out-dir "./reports/baseline_dev"
```

### A-share multifactor

```bash
quant-report run ^
  --adapter equity ^
  --output-root "D:/projects/a-share-multifactor/outputs" ^
  --run-id long_only_10k_retail_2025_now ^
  --strategy ols ^
  --plots equity
```

### Multi-run compare

```bash
quant-report compare ^
  --adapter equity ^
  --output-root "D:/projects/a-share-multifactor/outputs" ^
  --run-ids long_only_10k_retail_2025_now synthesis_compare_2025_now
```

## Plot groups

- **spread**: charts 01–15 (full futures diagnostics)
- **equity**: charts 01, 02, 12, 13, 16 (IC), 17 (synthesis curves)

## Legacy alias

`spread-viz` entry point remains available and points to the same CLI.

## Tests

```bash
pytest -q
```
