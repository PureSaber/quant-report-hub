# 成交参考价与原生现金账本归因

`cash-price-bridge`复用`cash-attribution`的原生账本、持仓、应收、费用和NAV核验。
它只将估值与成交损益代数拆分，不重放替代账户、不变更成交和费用，也不计算新的策略收益。
适用于单账户、单策略、同币种、单位乘数、多头现金证券。M5的`reconcile-v2`仍保留非负已入账费用契约。

## 独立报价包

由数据提供者准备独立目录，其中`references.json`显式绑定原生运行清单的SHA-256：

```json
{
  "schema_version": "quant-report-hub.execution-references/v1",
  "source_run_manifest_sha256": "<standard/v2/run_manifest.json的SHA-256>",
  "source": {
    "evidence_kind": "independently_observed",
    "provider": "<提供者>",
    "dataset_id": "<不可变数据集身份>",
    "description": "<来源、观察方式及已知限制>"
  },
  "policy": {
    "clock": "first_order_acceptance",
    "price": "last_available_midquote",
    "price_basis": "unadjusted_trade_currency",
    "max_quote_age_ms": 1000
  },
  "quotes": {"path": "quotes.csv", "sha256": "<报价CSV的SHA-256>"}
}
```

`evidence_kind`只能为`synthetic`、`model`或`independently_observed`，报告分别显示合成软件验证、
模型假设分析和独立观察的提供者声明。提供者、数据集身份、说明均必填。
来源声明及哈希不能自行认证数据真实、独立或时间戳正确；真实校准还需外部来源核验。
不得从成交价格反推“独立报价”，不得倒填可得时间。

`quotes.csv`列名及顺序固定：

```csv
quote_id,instrument_id,currency,observed_at,available_at,bid_price_units,bid_price_scale,ask_price_units,ask_price_scale,multiplier_units,multiplier_scale
q1,asset,CNY,2025-01-02T06:59:59Z,2025-01-02T06:59:59.500Z,999,2,1001,2,1,0
```

报价标识唯一，所有时点为UTC，观察时点不晚于可得时点。价格使用有符号64位整数units与0—18的scale，
买卖价格均为正、买价不大于卖价，乘数必须精确等于1。必须使用成交币种的未复权报价。
同证券、币种、可得时点重复的报价视为歧义并拒绝，不任意挑选。

每笔成交必须在原生`orders`及`order_events`中匹配账户、策略、证券、方向和唯一的首次接受事件
（`created → accepted`）。以接受时点选取最新已可得报价，最大报价年龄从`observed_at`计算，
配置范围为0—86400000毫秒。后续才可得的报价不会用于早先订单；全部成交必须覆盖。
部分成交共用原订单参考时点。报价观察至成交之间出现该证券原生公司行动时拒绝比较，
因为本契约不推断跨行动的价格或数量换算。所有引用原生数据的输出均在来源目录之外。

## 符号、舍入与对账

买入方向为+1、卖出为−1。对每笔成交：

```text
参考价 = (bid + ask) / 2
未舍入不利成本 = 方向 × 数量 × (成交价 − 参考价)
参考成交现金 = ROUND_HALF_EVEN(−方向 × 数量 × 参考价, 原生现金分录精度)
成交价差损益 = 原生成交现金 − 参考成交现金
舍入影响 = 成交价差损益 + 未舍入不利成本
```

买入10份，成交10元、参考9.9元：成交价差损益−1元；参考10.1元则为+1元。
卖出20份，成交6.2元、参考6.1元：成交价差损益+2元；参考6.3元则为−2元。
价格相同则为零。报价中点不预先截断，现金按原分录精度舍入；舍入可能使极小价差现金影响为零。

每个原生收益期间和证券分别满足：

```text
参考价估值剩余项 = 原估值与成交损益 − 成交价差损益
原净损益 = 参考价估值剩余项 + 成交价差损益 + 公司行动收益 + 原生费用现金影响
```

净损益、账本现金、持仓与估值保持原值；参考价剩余项不是可实现的替代账户。
订单接受到成交期间的行情变化包含在价差中，不能将全部差额称为纯滑点或市场冲击。
无成交时可以输出零覆盖、零价差的现金账本，但不产生执行质量结论。

## 生成与重算

```bash
quant-report cash-price-bridge --run-dir /path/to/run --references /path/to/quotes/references.json --references-sha256 <固定摘要> --out-dir /path/to/new-report
quant-report verify-cash-price-bridge --run-dir /path/to/run --references /path/to/quotes/references.json --references-sha256 <固定摘要> --report-dir /path/to/new-report --manifest-sha256 <报告manifest.json摘要>
```

输出保留原现金归因的四张表，并增加`fill_price_bridge.csv`、`instrument_price_bridge.csv`、
`period_price_bridge.csv`、HTML和清单。HTML区分证据性质、符号及解释范围，表格预览前100行，
完整CSV可下载。输入在读取和发布之间发生内容、大小、修改时间或原生文件集合变化时拒绝发布；
已有报告不可覆盖。验证命令重新读取原生输入与报价、重建全部表格及HTML，逐字节比较报告，
拒绝篡改、遗漏、额外文件和符号链接。生成与验证都不修改源输入。
