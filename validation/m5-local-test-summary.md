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
coverage report --include=quant_report_hub/attribution.py --fail-under=90
git diff --check
```

- `ruff check`：通过。
- `pytest -q`：37passed，4skipped；全仓分支覆盖率87.20%，超过80%。
- `coverage report`：`quant_report_hub/attribution.py`分支覆盖率90%，达到核心归因模块门禁。
- `git diff --check`：通过。

4个skip均为既有、非关键的本地外部市场数据/基线目录不存在，未新增skip。

负责人复核后补充了定点整数严格校验、账本费用反向核对、额外区间拒绝、残差component阈值以及统一入口的v2优先/v1回退测试；上述结果包含这些修复。

测试产生的绘图依赖warning未影响测试结果；后续可在非M5专项处理中统一处理第三方Seaborn/Pandas弃用warning。
