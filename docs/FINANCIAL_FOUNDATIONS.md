# 06 来源冲突裁决卡

安装 financial-data extra 后运行：
```powershell
quant-report source-resolution --decision path/to/decision.json
```
或调用 `quant_report_hub.source_reconciliation.resolution_card(path)`。验证 QDK qdk.source-adjudication/1 裁决及内含 case 的内容哈希；展示选用事实、裁决人、理由、证据 URI、前序快照及 requires_rerun 列表。篡改内容即拒绝，不把“已裁决”误称为“下游已验证”。

裁决在 QDK 生成；实际修正快照通过 apply_decision_snapshot 创建且不可覆盖旧数据。报告层不回写源数据、不自动启动订单或重算。测试见 tests/test_source_resolution.py。
