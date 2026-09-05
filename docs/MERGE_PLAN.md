# Merge Plan — spread-backtest-viz → quant-report-hub

**Status:** Phase 3 complete；`spread-backtest-viz`已于2026-09-05归档为只读
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

## Phase 3 — Archive ✅

1. `spread-backtest-viz` PR#1修复不可解析的PyPI依赖、加固CI，并在Python3.10/3.11/3.12通过；默认分支运行`33502122906`全绿
2. Single `spread-viz` entry point in hub `pyproject.toml` (already present)
3. Updated `quant-research-notes/repos.md` and lifecycle documentation
4. 维护者明确授权后创建两个annotated tag：恢复tag`spread-backtest-viz-v0.1.0-pre-merge`的tag object为`bed66d8f776a1d4cff0b062b8f80ebadf92f363b`，指向`cf492d3e73ceee712889e74dab0766e11cc48bee`；兼容tag`v0.2.0`的tag object为`a5bdd78e7dd789400f66b297acf5032c41d31973`，指向`8b80ceebe84492de60133f2f9432cf7f002f8327`
5. 2026-09-05归档[`PureSaber/spread-backtest-viz`](https://github.com/PureSaber/spread-backtest-viz)；仓库仍为public、保持无LICENSE、`archived=true`，Git历史、默认HEAD和两个tag对象均保留

## Rollback

Phase 2删除前计划的`spread-backtest-viz-v0.1.0-pre-merge`tag当时未实际创建。它是在2026-09-05经维护者明确授权后新建的恢复锚点，不是历史发布tag。若必须恢复写入，可先将仓库`archived=false`；若必须读取合并前实现，使用该恢复tag；最终兼容shim由`v0.2.0`固定。不得移动、重建或删除这两个tag。

See full analysis in quant-agent review session (2026-08-07).
