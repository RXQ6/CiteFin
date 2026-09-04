# 验证记录

## 2026-09-04：MVP 规格与黄金数据基线

### 验证范围

- `FEATURES.json` JSON 语法。
- `tests/golden/manifest.json` JSON 语法。
- 3 个 `expected.json` JSON 语法。
- manifest 中源文件 SHA-256。
- 每个用例事实唯一性。
- 资产=负债+权益。
- 毛利润=营业收入-营业成本。
- 15 项指标的独立 Decimal 复算。
- 零分母指标必须为 `null` 且包含原因。

### 执行方式

```powershell
& '<bundled-python>' tests\golden\validate.py
```

### 结果

```text
PASS G001_standard_profitable: facts=23 metrics=15
PASS G002_profit_cashflow_stress: facts=23 metrics=15
PASS G003_unit_and_zero_denominator: facts=23 metrics=15
PASS manifest: cases=3
```

### 结论

- 3 个合成源文件的哈希与 manifest 一致。
- 每个用例包含 23 个指标输入事实和 15 个预期指标。
- 正常、风险、百万元单位和零分母场景的预期结果复算通过。
- 当前基线可用于后续指标计算、数据契约和工作流冒烟测试。

### 已知限制

- 尚无产品代码、pytest、Make 或 CI；当前校验器是黄金数据自检工具，后续应接入 `make test`。
- 合成 Markdown 不能代表真实 PDF 表格解析表现。
- 尚无双人复核的真实年度报告，因此不能计算真实解析准确率。
- 尚未验证报告生成、证据引用正确性、Checkpoint 恢复或 Goal Gate。
