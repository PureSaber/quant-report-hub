# quant-report-hub

Unified visualization for spread and equity research outputs.

## Commands

```bash
pip install -e ".[dev]"
pytest -q
quant-report run --adapter equity --output-root ../a-share-multifactor/outputs --run-id RUN_ID --strategy ols --plots equity
quant-report run --adapter spread --output-root ../future_spread_analysis-team-framework/output --run-id RUN_ID
```

## Related

- [spread-backtest-viz](https://github.com/PureSaber/spread-backtest-viz)（deprecated compatibility shim；2026-09-05已归档为只读）
- [quant-research-notes](https://github.com/PureSaber/quant-research-notes)
