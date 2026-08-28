# quant-report-hub

`0.4.0`新增M5跨资产精确归因消费者。它只读取经`quant-lab v0.3.0`完整验证的
`standard/v2`Parquet运行产物；检测到v2存在但hash、schema或血缘损坏时立即失败，绝不回退到v1。

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

### Standard run attribution

The attribution command consumes the immutable `standard/` run contract. Position snapshots are
applied to later return periods by default, which prevents same-day look-ahead. It produces security
contribution, transaction-cost reconciliation, factor attribution, and optional Brinson-Fachler
allocation/selection/interaction effects.

```bash
quant-report attribute ^
  --run-dir "D:/projects/a-share-multifactor/outputs/demo" ^
  --asset-returns "asset_returns.csv" ^
  --factor-returns "factor_returns.csv" ^
  --benchmark-positions "benchmark_positions.csv" ^
  --classifications "industry.csv"
```

### `standard/v2`精确归因与NAV对账

`reconcile-v2`在运行目录外的独立报告目录发布`attribution.csv`、`reconciliation.csv`
和带hash的`manifest.json`；它不改写历史`standard/v1`或不可变的`standard/v2`。
金额全程使用`units + scale`转换的`Decimal`，并在account、portfolio、strategy和instrument
四层检查：

```text
delta NAV = price + carry + funding + roll + fx
            - commission - tax - maker_fee - taker_fee
            - slippage - market_impact - financing + residual
```

残差上限为`max(abs(deltaNAV)*1e-8,0.01基础币种单位)`。成本必须与`costs`及
`cash_ledger`精确相等；若有slippage，则必须提供同一`fill_id`的因果reference CSV，包含
`reference_time`、`available_at`、价格、合约乘数和FX快照。

```bash
quant-report reconcile-v2 ^
  --run-dir "D:/projects/quant-crypto-basis/outputs/demo" ^
  --out-dir "D:/reports/demo-m5" ^
  --slippage-references "D:/reports/slippage_references.csv"
```

归因认证范围是研究、回测与paper trading。国内L2仅在合法数据取得后可做市场数据认证；
真实交易、券商OMS/EMS和真实订单不在本仓认证范围内。

## Plot groups

- **spread**: charts 01–15 (full futures diagnostics)
- **equity**: charts 01, 02, 12, 13, 16 (IC), 17 (synthesis curves)

## Legacy alias

`spread-viz` entry point remains available and points to the same CLI.

## Tests

```bash
pytest -q
```
