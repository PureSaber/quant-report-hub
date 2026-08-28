# M5本地验证摘要

执行日期：2026-08-29（Asia/Shanghai）

## 依赖冻结

- `quant-lab @ v0.3.0`，注释tag对象为`63d11f0b26ad3ef272ef09476586a9e36ddbc347`，解引用commit为`ae0e9edea5cef136f9888d734030da1922b07283`。
- Python`3.12.5`本地验证环境；CI矩阵覆盖Python3.10、3.11、3.12。

## 实际命令和结果

```text
python -m pip install -e ".[dev]"
ruff check quant_report_hub/attribution.py quant_report_hub/cli.py quant_report_hub/__init__.py tests/test_v2_attribution.py tests/test_legacy_integration.py
pytest -q
pytest -q --cov-report=json:coverage.json
读取coverage.json并校验quant_report_hub/attribution.py纯分支覆盖率>=90%
pytest -q H:/Documents/ChatGPT/temp/puresaber-quant-platform/validation-logs/m5/independent/audit-20260829-m5-final/test_independent_m5_regressions.py
git diff --check
```

- `ruff check`：通过。
- `pytest -q --cov-report=json:coverage.json`：39passed，4skipped；全仓覆盖率88.93%，超过80%。
- `coverage.json`纯分支计数：`quant_report_hub/attribution.py`为190/210=90.48%，达到核心归因模块门禁。
- 独立M5回归：6passed，覆盖报告目录隔离、来源成本拒绝和虚构标的拒绝等审计发现。
- `git diff --check`：通过。

4个skip均为既有、非关键的本地外部市场数据/基线目录不存在，未新增skip。

负责人复核后补充了定点整数严格校验、账本费用双向聚合核对、额外区间拒绝、
残差component阈值、输出目录隔离、标的来源可追溯和独立instrument期望值对账，
以及统一入口的v2优先/v1回退测试；上述结果包含这些修复。CI门禁读取coverage.py
JSON的纯分支计数，不再把语句覆盖率混入核心分支门禁。

测试产生的绘图依赖warning未影响测试结果；后续可在非M5专项处理中统一处理第三方Seaborn/Pandas弃用warning。
