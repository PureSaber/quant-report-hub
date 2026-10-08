# 成交成本的时间留出诊断

`quant-report execution-cost-diagnostics`在已有原生现金账本与报价桥接之上，生成可重算的逐订单组诊断、CSV与HTML。它不改写账户，也不把历史拟合转换成自然前向证据。

输入为已核验的原生`standard/v2`运行目录、[执行参考报价](CASH_PRICE_BRIDGE.md)及调用者给定的原始字节SHA-256。当前范围沿用现金价格桥接：单币种、多头现金证券、订单接受时已可得的报价中点。费用现金影响单独展示，不与原账本净损益再次相加。

另提供一个严格JSON策略文件，六个字段全部必需：

```json
{
  "schema_version": "quant-report-hub.execution-cost-policy/v1",
  "training_end": "2025-01-31T15:00:00+08:00",
  "holdout_start": "2025-02-01T00:00:00+08:00",
  "minimum_train_orders": 20,
  "minimum_holdout_orders": 10,
  "adverse_budget_bps": "50"
}
```

以上日期、最小样本数和预算只是格式示例，应依据研究计划指定。策略文件及其哈希不证明曾事前登记。

```text
quant-report execution-cost-diagnostics --run-dir RUN --references REFERENCES_JSON --references-sha256 REFERENCES_SHA256 --policy POLICY_JSON --policy-sha256 POLICY_SHA256 --out-dir NEW_REPORT
quant-report verify-execution-cost-diagnostics --run-dir RUN --references REFERENCES_JSON --references-sha256 REFERENCES_SHA256 --policy POLICY_JSON --policy-sha256 POLICY_SHA256 --report-dir NEW_REPORT --manifest-sha256 REPORT_MANIFEST_SHA256
```

同一订单的部分成交只算一个观察组。接受及最后成交均不晚于训练截止的组进入训练；接受早于截止、但跨截止成交的组整体排除。接受时点不早于留出起点的组进入留出；中间空档排除。观察组并不保证统计独立，不能用其数量直接推导显著性。

有符号不利成本沿用逐笔报价桥接：买入价高于参考价为正，卖出价低于参考价为正，改善为负。训练估计为`10000 × 训练总有符号成本 / 训练总参考名义金额`。留出仅接受训练估计，不参与拟合；其实际基点与训练估计之差为留出预测偏差。按参考名义金额加权，不能将买卖成本取绝对值后混为冲击。

训练样本不足时不输出拟合值；留出样本不足时保留描述性实测值，但不输出总体预测偏差，状态为`insufficient_samples`。没有成交为`no_trades`。CLI成功计算退出0，样本不足/无成交退出2，输入或核验失败退出1。最小组数只是调用者的样本门槛，不是统计认证。

输出为`orders.csv`、`summary.json`、`report.html`和`manifest.json`，HTML预览前100组，CSV保留全部。发布只能进入来源之外的新目录；输入变化或已有目录均拒绝。核验重新读取原账本、报价及策略，全量重算并逐字节比较产物；只修改产物再重算其哈希不能通过。

报告始终包含`real_execution_calibrated=false`与`new_forward_evidence=false`。相对接受时报价的价差包含后续行情变化，并非纯市场冲击；合成/模型报价只验证软件或假设，独立观察标签仍是提供者声明。这里不拟合借券、税收、FX、保证金、成交概率或容量曲线，也不自动更改成本参数和风险限额。
