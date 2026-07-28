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

- [spread-backtest-viz](../spread-backtest-viz) (legacy, unchanged)
- [quant-research-notes](../quant-research-notes)
