# M6本地验证摘要

执行日期：2026-08-29（Asia/Shanghai）

## 范围

- 基线：`origin/main`的`f3b2fb1d4a9770c9ecc4f4633e7765198c62a9ee`。
- 分支：`codex/cross-asset-v2-m6-governance`。
- 版本：`0.4.0`至`0.4.1`。
- `quant-lab v0.3.1`为已发布注释tag；`git ls-remote --tags`确认其peeled commit为
  `27489d270e132adbec1bced93eb2ae84ad5e1a9b`。

## 实际命令与结果

```text
python -m pip install --requirement requirements.lock
python -m pip check
python -m pip install --no-deps --no-build-isolation --editable .
python -m pip check
ruff check quant_report_hub tests scripts
ruff format --check quant_report_hub tests scripts
pytest -q --cov-report=json:coverage.json
python scripts/check_coverage.py coverage.json
git diff --check
```

- 隔离Python3.12.5环境中，两次`pip check`均返回`No broken requirements found.`。
- 锁文件中的VCS安装日志确认`quant-lab`解析至`27489d270e132adbec1bced93eb2ae84ad5e1a9b`。
- Ruff检查和格式检查均通过。
- 测试结果：`42 passed, 4 skipped`；4个skip均为既有的本地外部市场数据/基线目录条件，未新增skip。
- 全仓覆盖率：`88.93%`，高于80%门禁。
- `quant_report_hub/attribution.py`纯分支覆盖率：`190/210 = 90.48%`，高于90%门禁。
- `coverage.json`在Windows以反斜杠写入模块路径；门禁脚本已按平台归一化路径，并补充回归测试。

Python3.10、3.11和3.12的同一安装、Ruff、测试与覆盖率流程由`.github/workflows/ci.yml`
的PR矩阵执行；本地仅安装了3.12解释器。首次PR矩阵发现`contourpy 1.3.3`要求Python>=3.11，
因此锁已精确调整为兼容3.10的`contourpy 1.3.2`并重新触发矩阵。
