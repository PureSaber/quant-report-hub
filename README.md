# quant-report-hub

本开发分支在`0.4.1`的绘图与精确归因能力上增加只读研究看板。它只读取经固定版本`quant-lab`
完整验证的`standard/v2`Parquet运行产物；检测到v2存在但hash、schema或血缘损坏时立即失败，绝不回退到v1。

Unified visualization hub consolidated from [`spread-backtest-viz`](https://github.com/PureSaber/spread-backtest-viz). The legacy repository contains only a deprecated compatibility shim pinned to this repository's validated commit and was archived read-only on 2026-09-05; new integrations must use `quant-report-hub` directly.

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
固定；内部`quant-lab`在项目元数据和锁中均指向不可变提交
`938927e5bcad641d46e3bd733e6323719d44aa50`，包含零成交空表校验、失败决策索引与不可变试验登记。
这是研究决策工作流已采用的提交，旧发布tag保持不变，禁止使用浮动分支。CI在Python3.10、
3.11和3.12上均先按锁安装、执行前后`pip check`，再以`--no-deps --no-build-isolation`
安装editable项目。

重建锁文件时，使用干净Python 3.10环境运行，以包含最低支持版本所需的条件依赖
（exceptiongroup、tomli及其依赖）：

```bash
pip-compile --allow-unsafe --build-deps-for=editable --constraint=requirements-constraints.txt \
  --extra=dev --output-file=requirements.lock --strip-extras pyproject.toml
```

`requirements-constraints.txt`只记录Python3.10—3.12共同解析所需的上界，不作为第二套
安装输入。锁生成后必须核对`quant-lab`实际解析至上述commit，并运行完整测试、`python scripts/check_coverage.py coverage.json`、
`pip check`及3.10/3.11/3.12 CI矩阵。全仓分支覆盖率门禁为80%，`attribution.py`承担归因、
对账和报告发布核心逻辑，其纯分支覆盖率门禁为90%。不得通过新增skip或排除核心代码规避门禁。

此版本不改变价格、Carry、Funding、Roll、FX、commission/tax/maker/taker费用、slippage、
market impact、financing或residual的归因语义。若需要回滚，
回退到上一个默认分支提交及其`requirements.lock`，并重新按该锁安装；不得移动已有tag或改写
已发布的`standard/v2`输入和归因报告。

## Adapters

| Adapter | Source projects | Output layout |
|---------|-----------------|---------------|
| `spread` | quant-futures-spread | `output/<run_id>/daily/portfolio/...` |
| `equity` | a-share-multifactor, sklearn-stock-trend | `outputs/<run_id>/capital_curves.csv` |

## Usage

### 统一研究看板

```powershell
quant-report dashboard --decision-root ../review-runs --out reports/dashboard.html

# 可选：先由 quant-lab 建立实验索引，再以只读方式接入报告。
quant-lab --db reports/experiments.db scan --root ../review-runs --project a-share-multifactor
quant-report dashboard --decision-root ../review-runs --lab-db reports/experiments.db --out reports/dashboard.html
```

`--decision-root`可重复指定多个独立账户／策略的输出目录。浏览器打开生成的HTML即可使用，
页面内置样式与交互，无CDN、服务器或外网请求。包含最新决策、模拟持仓、拟调仓及成本、
风险与验证详情、历史运行、实验筛选和所选实验指标并列对比；所有指标来自产物，不重新计算收益。

- 每个目录只认`latest.json`。最新文件缺失、损坏或状态不一致时显示来源不可用，绝不自动采用旧成功结果。
- 检查`quant.decision/v1`字段、模拟范围和带时区的时点；纸面可用决策必须通过所引用`standard/v2`
  清单hash、运行身份、代码版本及完整产物校验。该检查不是对决策JSON的数字签名或策略收益认证。
- 过期、阻断、仅观察及历史记录不显示当前拟调仓。浏览器每15秒检查有效期；JavaScript关闭时拟调仓默认隐藏。
- 页面是生成时的静态快照，**生产者运行后须重新执行dashboard命令**才能反映新结果。
  报告生成成功只表示HTML已生成，不能根据命令退出码认定策略或数据可用，应查看各来源状态。
- SQLite索引以`mode=ro`读取，不创建／更新实验数据库。存在标准产物时重新校验并读取来源指标，
  无法验证时不采用缓存；无标准产物的旧实验明确标记为未校验缓存。
- 输出HTML必须位于决策目录、已载入实验目录之外。页面原子替换；单份JSON上限8MiB，
  每个目录最多载入200条历史记录，实验索引最多载入最近200条。
- 证据链接使用本地相对路径，原始JSON、配置、账本和验证文件需保留原目录关系。
  看板不会启动策略、修改模拟账户或发送订单。

详细流程见[研究看板说明](docs/RESEARCH_DASHBOARD.md)。

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
