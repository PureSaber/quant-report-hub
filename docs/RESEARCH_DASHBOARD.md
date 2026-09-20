# 研究看板

`quant-report dashboard`将已有研究产物汇总为本地静态HTML和机器可读异常sidecar。数据获取、策略计算、账户推进继续
由原组件负责，报告层只读取结果。原有`run`、`compare`、`attribute`和`reconcile-v2`命令保持兼容。

## 每次收盘后的使用顺序

1. 在策略项目中运行原决策工作流，写出本次决策和`latest.json`。工作流失败时也应写出阻断卡。
2. 可选运行`quant-lab scan`更新实验索引。索引的创建和更新属于quant-lab，不由看板隐式执行。
3. 运行一次`quant-report dashboard`，或长期运行`quant-report serve`自动重建并刷新HTML。

```powershell
quant-report dashboard --decision-root ../review-runs --lab-db reports/experiments.db --out reports/dashboard.html
quant-report serve --decision-root ../review-runs --lab-db reports/experiments.db --out reports/dashboard.html --port 8767
```

全部路径相对于执行命令的当前目录。`latest.json`中的相对decision路径相对于其所在决策根目录，
绝对路径也可读取，但必须指向该目录中同一run_id的`decision.json`。决策证据中的相对账本路径
相对于该运行目录。缺失实验索引只影响实验区，决策区仍可显示；缺失决策目录会显示明确的错误卡。

## 页面

- 决策收件箱：按来源异常、运行阻断、过期、可继续模拟和仅观察排列最新运行，可按来源、状态、
  项目、策略和run_id筛选，并直接跳转到详情。
- 最新决策：行情截止时间、有效期、生产者状态、目标标的、拟调仓、预计成本和前向观察天数。
- 模拟账户：现有持仓和仍在有效期内的最新拟调仓；预计费用保持生产者估计值。
- 决策变化：当前目标与最近一条可验证且曾为`paper_ready`的历史决策逐标的比较，区分新增、退出、
  增持、减持和不变，并标记配置hash或代码版本变化。`blocked`和`observe`的空目标不会被解释为
  清仓；没有历史基准时明确显示首次可比较决策。
- 计划与实际：按`order_id`连接拟调仓和已校验标准订单，核对证券、方向、数量和累计成交，展示
  成交比例、平均成交价、实际成本及执行后的模拟持仓。系统会继续检查同一目录中版本、配置、策略和
  账户口径一致的后续运行，因此上一日接受的订单可在下一日账本中闭环；累计账本按`fill_id`和
  `cost_id`去重。订单已接受不等于成交。
- 前向效果：仅在生产者声明足够`forward_observation_days`、运行只有一个策略且标准净收益序列
  满足一日一条时，计算1／5／20日复合净收益；未成熟窗口保持“—”。
- 实验与证据：按项目或run_id搜索，查看来源状态，勾选至少两个实验并列查看指标。
- 风险与异常：把目标集中度、现金缓冲、回撤和预计成本／净值转为可读摘要；来源损坏、生产阻断、
  过期、执行证据不一致和限制突破进入异常列表。等待下一交易日成交和观察窗口未成熟标为进度信息。
- 模拟账户汇总：从最新`portfolio_snapshots`按账户展示净值、现金、市值、订单进度和需处理异常；
  `--decision-root`可重复指定，用于汇总多个账户或策略目录。
- 历史记录：旧决策保留用于复盘，拟调仓不展示为当前操作。
- 证据：直接打开决策、标准清单、配置和指标，下载或读取订单、成交与现金账本Parquet。

空的Sharpe或年化收益显示为“—”，不会用0或历史回测结果替换。多组合实验保留每个组合的
来源指标，不自动挑选收益最好的一组。比较时需检查日期区间、币种、收益频率和成本配置。
没有成交时成交数量显示为0但成交价和实际成本保持为空；没有足够前向观察时1／5／20日收益保持为空。

## 时效与完整性

最新指针损坏、版本不支持、运行身份错配或账本篡改时显示“来源不可用”，不会回退到历史成功卡。
`blocked`代表生产者运行阻断，`observe`代表仅观察，`paper_ready`只表示可继续模拟。
报告层单独计算展示状态`expired`，不改写源决策。页面首次加载及每15秒会按浏览器时间检查有效期。
停用JavaScript时拟调仓默认隐藏。生成时已过期的页面需重新生成，修改本机时间不会恢复其拟调仓。

静态HTML自身不读取源目录；`serve`监视文件元数据，重建后更新`*.status.json`，页面每5秒检查并自动
刷新。`dashboard`模式下，生产者完成后仍需再次运行命令。内容与链接适合本机使用，
不应把复制出的单个HTML当作包含完整数据的独立归档。只读校验验证来源完整性，不证明市场数据PIT
语义、策略有效性，也不为未签名的decision.json提供身份认证。

当前支持`quant.decision/v1`的模拟决策，以及quant-lab现有SQLite索引结构；不接收真实交易授权状态。
页面不写审批意见、不修改策略参数，也不启动回测；这些控制操作应由独立的工作台负责。
零成交账本依赖quant-lab固定提交`c8d73813fe6a631a21811182804b3e3b857839d8`的空表校验修复。

## 异常接入和日报包

`dashboard`和`serve`在HTML旁发布`<name>.alerts.json`与`<name>.html.status.json`。异常文件使用
`quant-report-hub.alerts/v1`，每条记录包含稳定的`alert_id`、严重级别、代码、来源、运行编号、说明和
证据路径。通知器可以只转发`critical`和`warning`；`info`用于显示等待成交或观察窗口成熟进度。

```powershell
quant-report daily-package `
  --decision-root ../review-runs `
  --lab-db reports/experiments.db `
  --out-dir reports/daily-2026-09-20
```

日报包包括HTML、打印版PDF、`decisions.csv`、`execution.csv`、`outcomes.csv`、`accounts.csv`、
`alerts.csv`、JSON sidecar和`manifest.json`。CSV使用UTF-8 BOM以便Excel直接打开；manifest记录除自身
外每个文件的字节数和SHA-256。PDF依赖本机Edge或Chromium；只有明确不需要PDF的自动化环境才使用
`--no-pdf`。
