# Merge Plan — spread-backtest-viz → quant-report-hub

**Status:** Proposed (Phase 1 ready)  
**Canonical package:** `quant-report-hub`

## Duplication

Core loader/metrics/plots ~99% identical. Hub adds equity adapter + plot registry.

## Phase 1 — Compatibility shim (1 week)

1. `spread-backtest-viz` depends on `quant-report-hub>=0.2.0`
2. `spread_viz/cli.py` re-exports hub CLI + `DeprecationWarning`
3. Parity tests in `quant-report-hub/tests/test_spread_parity.py`
4. Deprecation banner in spread-backtest-viz README

## Phase 2 — Consolidate (1–2 weeks)

1. Delete duplicated modules from spread-backtest-viz (keep shim only)
2. health-check: viz tests only on hub
3. Optional pipeline viz step

## Phase 3 — Archive (1 week)

1. Archive `PureSaber/spread-backtest-viz` on GitHub
2. Single `spread-viz` entry point in hub `pyproject.toml`
3. Update `quant-research-notes/repos.md`

## Rollback

Tag `spread-backtest-viz-v0.1.0-pre-merge` before Phase 2 deletions.

See full analysis in quant-agent review session (2026-08-07).
