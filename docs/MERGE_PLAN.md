# Merge Plan — spread-backtest-viz → quant-report-hub

**Status:** Phase 2 complete；Phase 3 technical readiness complete，tag/archive待维护者明确批准
**Canonical package:** `quant-report-hub`

## Duplication

Core loader/metrics/plots ~99% identical. Hub adds equity adapter + plot registry.

## Phase 1 — Compatibility shim ✅

1. `spread-backtest-viz` pins the exact validated `quant-report-hub` commit because the package is not published to PyPI
2. `spread_viz/cli.py` delegates to hub + `DeprecationWarning`
3. Parity tests in `quant-report-hub/tests/test_spread_parity.py`
4. Deprecation banner in spread-backtest-viz README

## Phase 2 — Consolidate ✅

1. Deleted duplicated modules from spread-backtest-viz (shim only: `spread_viz/cli.py`)
2. health-check: viz tests on hub; spread-backtest-viz runs shim tests only
3. Optional pipeline viz step — pending

## Phase 3 — Archive（technical readiness complete；owner approval pending）

1. `spread-backtest-viz` PR#1修复不可解析的PyPI依赖、加固CI，并在Python3.10/3.11/3.12通过；默认分支运行`33502122906`全绿
2. Single `spread-viz` entry point in hub `pyproject.toml` (already present)
3. Update `quant-research-notes/repos.md` and lifecycle documentation
4. 经维护者明确批准后创建恢复/兼容tag并保存tag object证据；不得声称恢复tag历史上已存在
5. 经维护者明确批准后archive `PureSaber/spread-backtest-viz`；归档只设为只读，不删除Git历史

## Rollback

Phase 2删除前计划的`spread-backtest-viz-v0.1.0-pre-merge`tag从未实际创建。删除前提交`cf492d3e73ceee712889e74dab0766e11cc48bee`仍可由默认分支历史到达；只有维护者明确批准后才可创建新的annotated恢复tag，并必须如实记录创建时间，不得伪称其历史上存在。最终绿色shim HEAD为`8b80ceebe84492de60133f2f9432cf7f002f8327`。

See full analysis in quant-agent review session (2026-08-07).
