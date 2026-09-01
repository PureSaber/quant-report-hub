# quant-report-hub

`0.4.1`将M5跨资产精确归因消费者纳入M6依赖治理。它只读取经`quant-lab v0.3.1`
完整验证的`standard/v2`Parquet运行产物；检测到v2存在但hash、schema或血缘损坏时立即失败，绝不回退到v1。

Unified visualization hub consolidated from [`spread-backtest-viz`](https://github.com/PureSaber/spread-backtest-viz). The legacy repository now contains only a deprecated compatibility shim pinned to this repository's validated commit; new integrations must use `quant-report-hub` directly.

## Install

```bash
cd quant-report-hub
python -m venv .venv
.venv\Scripts\activate
python -m pip install --requirement requirements.lock
python -m pip check
python -m pip install --no-deps --no-build-isolation --editable .
python -m pip check
```

## 依赖与契约治理

`pyproject.toml`的`[tool.quant-workspace]`声明本仓库属于`reporting`层：消费
`standard/v2@2.0.0`和`puresaber.run-manifest@2.0.0`，并生产
`quant-report-hub.attribution-report@2.0`（独立报告目录中的`manifest.json`、
`attribution.csv`和`reconciliation.csv`）。`standard/v2`及其run manifest先由
`quant-lab`校验hash、schema和血缘，报告代码随后才读取Parquet；因此输入契约损坏不会降级为v1。

`requirements.lock`是运行时、开发和editable构建环境的唯一锁文件。所有PyPI依赖均精确
固定；内部`quant-lab`在项目元数据和锁中均指向已发布的注释tag`v0.3.1`，其peeled
commit经验证为`27489d270e132adbec1bced93eb2ae84ad5e1a9b`，禁止使用任何浮动分支。CI在Python3.10、
3.11和3.12上均先按锁安装、执行前后`pip check`，再以`--no-deps --no-build-isolation`
安装editable项目。

重建锁文件时，使用干净环境运行：

```bash
pip-compile --allow-unsafe --build-deps-for=editable --constraint=requirements-constraints.txt \
  --extra=dev --output-file=requirements.lock --strip-extras pyproject.toml
```

`requirements-constraints.txt`只记录Python3.10—3.12共同解析所需的上界，不作为第二套
安装输入。锁生成后必须核对`quant-lab@v0.3.1`实际解析至上述commit，并运行完整测试、`python scripts/check_coverage.py coverage.json`、
`pip check`及3.10/3.11/3.12 CI矩阵。全仓分支覆盖率门禁为80%，`attribution.py`承担归因、
对账和报告发布核心逻辑，其纯分支覆盖率门禁为90%。不得通过新增skip或排除核心代码规避门禁。

此版本不改变价格、Carry、Funding、Roll、FX、commission/tax/maker/taker费用、slippage、
market impact、financing或residual的归因语义；它只收紧来源契约和依赖可复现性。若需要回滚，
回退到上一个默认分支提交及其`requirements.lock`，并重新按该锁安装；不得移动已有tag或改写
已发布的`standard/v2`输入和归因报告。

## Adapters

| Adapter | Source projects | Output layout |
|---------|-----------------|---------------|
| `spread` | quant-futures-spread | `output/<run_id>/daily/portfolio/...` |
| `equity` | a-share-multifactor, sklearn-stock-trend | `outputs/<run_id>/capital_curves.csv` |

## Usage

### Futures spread (same as spread-backtest-viz)

```bash
quant-report run ^
  --adapter spread ^
  --output-root "<workspace>/quant-futures-spread/output" ^
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

`reconcile-v2`在`run/standard`之外的独立报告目录发布`attribution.csv`、
`reconciliation.csv`和带hash的`manifest.json`；输出目录等于或位于`run/standard`
之下时会直接拒绝发布，因此不会改写历史`standard/v1`或不可变的`standard/v2`。
金额全程使用`units + scale`转换的`Decimal`，并在account、portfolio、strategy和instrument
四层检查：

```text
delta NAV = price + carry + funding + roll + fx
            - commission - tax - maker_fee - taker_fee
            - slippage - market_impact - financing + residual
```

残差上限为`max(abs(deltaNAV)*1e-8,0.01基础币种单位)`。每个成本component必须在
`costs`、`cash_ledger`和来源归因中按原币及基础币聚合后精确相等，任一侧多出、缺失或
金额不符都会拒绝发布。instrument层对账只接受可从positions、fills、costs、margin或
orders追溯的标的，并使用来源归因生成独立期望值；若有slippage，则必须提供同一
`fill_id`的因果reference CSV，包含`reference_time`、`available_at`、价格、合约乘数和FX快照。

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
