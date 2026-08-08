# Merge Plan — spread-backtest-viz → quant-report-hub

**Status:** Phase 2 complete (shim only in spread-backtest-viz)  
**Canonical package:** `quant-report-hub`

## Duplication

Core loader/metrics/plots ~99% identical. Hub adds equity adapter + plot registry.

## Phase 1 — Compatibility shim ✅

1. `spread-backtest-viz` depends on `quant-report-hub>=0.2.0`
2. `spread_viz/cli.py` delegates to hub + `DeprecationWarning`
3. Parity tests in `quant-report-hub/tests/test_spread_parity.py`
4. Deprecation banner in spread-backtest-viz README

## Phase 2 — Consolidate ✅

1. Deleted duplicated modules from spread-backtest-viz (shim only: `spread_viz/cli.py`)
2. health-check: viz tests on hub; spread-backtest-viz runs shim tests only
3. Optional pipeline viz step — pending

## Phase 3 — Archive (pending)

1. Archive `PureSaber/spread-backtest-viz` on GitHub
2. Single `spread-viz` entry point in hub `pyproject.toml` (already present)
3. Update `quant-research-notes/repos.md` — done locally

## Rollback

Tag `spread-backtest-viz-v0.1.0-pre-merge` before Phase 2 deletions.

See full analysis in quant-agent review session (2026-08-07).
