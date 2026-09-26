# 研究比较报告

`python -m quant_report_hub.research_workbench ../studies/example/study.json --output ../studies/example/research.html`

先只读核对SQLite预登记、全部候选、结果哈希和候选产物哈希，再生成可筛选HTML及diagnostics.json。失败实验同样展示，不允许通过删除候选制造漂亮报告。可查看成本后收益、回撤、费用、成交数、因子覆盖/IC衰减、子段、冗余及冻结配方。

主实验与同投入上限买入持有做同口径比较；成本压力明确列为口径变化，配对扰动用于诊断而不自动选最高收益。合成行情和fixture-only结果明确标识软件验证；短窗口、固定观察池、初始资金份额和非独立留出等限制保留在报告中。
