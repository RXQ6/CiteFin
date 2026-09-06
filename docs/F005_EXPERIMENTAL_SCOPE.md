# F005 实验分支范围

## 当前定位

本分支 `codex/f005-experimental` 只验证 F005“财务字段标准化”的工程契约，不改变主线 `FEATURES.json` 中 F004/F005 的正式验收状态。F004 真实样本独立复核仍未完成，因此本分支不声明真实中文年报准确率。

## 已实现

- `FinancialFact` 持久化实体和 `20260906_0005` Alembic 迁移；
- F004 `located + consolidated` 结果作为 F005 输入前置；
- 中文/英文核心报表行标签的版本化确定性映射；
- `yuan`、`thousand_yuan`、`million_yuan` 到元的 `Decimal` 换算；
- 原始标签、原始值、标准值、期间、币种、单位、口径、页码和定位字段同时保留；
- 同一事实粒度的重复请求幂等；冲突值生成 `conflict_group_id`，不覆盖原始值；
- `POST /api/v1/analysis-runs/{run_id}/documents/{source_id}/facts/normalize` 接口。

## 明确不做

- 不把未经独立复核的真实年报作为黄金数据；
- 不声明中文年报语义准确率；
- 不实现 F006 指标计算、风险规则、报告生成或交易能力；
- 不修改 F004 识别算法。

## 促进正式晋级的条件

F004 完成独立复核和 Goal Gate 后，重新运行 F004→F005 集成验收；确认真实输入策略、映射覆盖率和冲突统计后，才能把本分支提升为正式 F005。
