# CiteFin 项目状态

[English](PROJECT_STATUS.en.md) | 简体中文

> 截至 2026-09-08。本页是面向 GitHub 访客的状态摘要；功能状态以根目录
> [`FEATURES.json`](../FEATURES.json) 为准，验证细节以
> [`VALIDATION.md`](VALIDATION.md) 为准。

## 结论

CiteFin 的 F001–F018 MVP 工程实现和完整财报研究工作台已经完成，但项目尚未达到正式生产验收状态。

- 18/18 个功能已有工程实现，没有 `not_started` 项。
- F001–F003 为 `verified`。
- F004 为 `provisional`。
- F005–F018 为 `candidate_complete`。
- 完整自动化门禁通过：137 项 pytest、91.40% 覆盖率、Ruff、格式检查、严格 mypy、3/3 合成黄金用例和 JavaScript 语法检查。
- 本地 `main` 已与 GitHub `origin/main` 同步。

`candidate_complete` 表示工程实现及现有机器验证已经完成，不等于正式外部验收，也不得被解释为真实中文年报准确率已经得到验证。

## 已实现能力

| 范围 | 状态 | 已实现知识与能力 |
| --- | --- | --- |
| F001–F003 | `verified` | 工程基线、运行健康检查、PDF 上传与不可变存储、分页文本及表格候选解析 |
| F004 | `provisional` | 合并资产负债表、利润表和现金流量表识别，歧义保留及人工确认边界 |
| F005–F007 | `candidate_complete` | Decimal 财务事实标准化、15 项确定性指标、Claim–Evidence 可追溯关系 |
| F008–F010 | `candidate_complete` | 类型化工作流状态、证据支持的财务分析声明、确定性风险识别 |
| F011–F013 | `candidate_complete` | 结构化报告、独立 Evaluator、唯一 Goal Gate 与失败修复路由 |
| F014–F015 | `candidate_complete` | Checkpoint 保存与恢复、运行进度、有限 SSE 事件和游标重连 |
| F016–F018 | `candidate_complete` | 完整前端工作台、PDF 页级证据查看、合成成功/失败端到端验收 |

工作台只读取真实持久化实体，不使用模拟数据生成进度或完成状态。用户可以分阶段执行上传、解析、报表识别、人工事实确认、指标计算、财务分析、风险识别、报告生成、Evaluator、Goal Gate 和 Checkpoint 恢复。

## 尚未完成的生产化工作

- F004 真实年报 Reviewer A/B 双人独立盲审、冲突裁决及证据封存。
- F005–F018 的真实数据复核与正式外部 Goal Gate。
- 自动表格字段抽取；当前部分财务事实需要人工确认。
- 完整 LangGraph 自动执行器和所有节点后的自动 Checkpoint。
- 正式用户认证；当前 `X-User-ID` 仅为开发环境隔离边界。
- 生产级长连接事件推送、多实例事件总线、对象存储和数据库级审计保护。
- 真实年报准确率、证据定位准确率及生产浏览器矩阵验证。

## 验证边界

当前端到端验收使用可复现的合成 PDF、契约数据和经公开 API 提交的人工事实。合成流程中的重大 Claim 页级证据覆盖率为 100%，但该结果仅适用于该合成样本，不能外推为真实年报表现。

CiteFin 不执行交易、下单、转账或账户操作，不承诺收益，也不输出无证据的个性化投资建议。

## 本地运行

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 migrate
.\scripts\dev.ps1 test
.\scripts\dev.ps1 run
```

启动后访问 `http://127.0.0.1:8000/` 使用工作台。
