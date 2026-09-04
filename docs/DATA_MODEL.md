# MVP 数据模型

## 1. 设计原则

1. 原始事实、标准化事实、计算结果、模型推断和最终表达必须分层存储。
2. 任何重大数字和结论都必须能够沿 `Claim → Evidence → SourceDocument` 回溯。
3. 金融数据必须携带公司、期间、币种、单位、口径和数据截止时间。
4. 原始文件和原始提取值不可覆盖；修正通过新版本和审计事件表达。
5. LLM 不得写入 `FinancialFact` 或 `CalculatedMetric` 的已验证字段。
6. 所有实体使用稳定 ID；外部展示不得依赖数据库自增序号。

## 2. 关系概览

```text
AnalysisRun
├── Task
├── SourceDocument
│   ├── DocumentPage
│   └── FinancialFact
├── CalculatedMetric ── MetricDefinition
├── Claim
│   └── Evidence ── FinancialFact / CalculatedMetric / SourceLocator
├── RiskFinding ── Claim
├── Report ── Claim
├── Evaluation
├── Approval
├── AuditEvent
└── WorkflowCheckpoint
```

## 3. 通用约定

### 3.1 ID

- `run_id`: `run_<uuid7>`
- `task_id`: `task_<uuid7>`
- `source_id`: `src_<uuid7>`
- `fact_id`: `fact_<uuid7>`
- `metric_id`: `metric_<uuid7>`
- `claim_id`: `claim_<uuid7>`
- `evidence_id`: `ev_<uuid7>`
- `report_id`: `report_<uuid7>`
- `evaluation_id`: `eval_<uuid7>`

### 3.2 时间

- 数据库统一保存 UTC ISO 8601 时间。
- `as_of` 表示本次分析允许使用信息的截止时刻。
- `period_start`、`period_end` 表示财务数据所属期间。
- `published_at` 表示来源公开时间；未知时为 `null`，不能用抓取时间代替。

### 3.3 数值

- 金额和比率使用十进制数，不使用二进制浮点作为持久化真值。
- `raw_value` 保留报告披露数字，`normalized_value` 统一换算为基础币种最小单位。
- `display_unit` 使用受控枚举：`yuan`、`thousand_yuan`、`million_yuan`。
- 比率内部使用小数，例如 20% 存为 `0.20`。

## 4. 核心实体

### 4.1 AnalysisRun

一次用户分析请求及其完整生命周期。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `run_id` | string | 主键 |
| `idempotency_key` | string | 用户范围内唯一 |
| `user_id` | string | 必填 |
| `company_name` | string | 必填，可在确认前修正 |
| `security_code` | string | A 股代码格式；必填 |
| `report_period_end` | date | 必填 |
| `as_of` | datetime | 必填 |
| `analysis_focus` | enum[] | `comprehensive/profitability/cashflow/solvency` |
| `status` | enum | 见状态机 |
| `current_node` | string/null | 当前工作流节点 |
| `model_profile` | string | 模型配置版本 |
| `workflow_version` | string | 必填 |
| `created_at` | datetime | 必填 |
| `updated_at` | datetime | 必填 |
| `completed_at` | datetime/null | 仅终态可写 |
| `failure_code` | string/null | 失败时必填 |

状态机：

```text
created → validating → running → candidate_complete → evaluating → verified
                         ├────────→ awaiting_user
                         ├────────→ revision_required → running
                         ├────────→ blocked
                         └────────→ failed
```

只有 Goal Gate 可以写入 `verified`。

### 4.2 Task

持久化任务图中的原子工作单元。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `task_id` | string | 主键 |
| `run_id` | string | 外键 |
| `feature_id` | string | 对应 `FEATURES.json` |
| `task_type` | string | 受控类型 |
| `title` | string | 必填 |
| `status` | enum | `not_started/ready/in_progress/blocked/candidate_complete/verified/failed` |
| `owner` | string/null | `in_progress` 时必填 |
| `blocked_by` | string[] | 任务 ID 列表 |
| `attempt_count` | integer | 非负 |
| `acceptance_rule` | object | 机器可读验收条件 |
| `evidence_refs` | string[] | 完成证据 ID |
| `error` | object/null | 结构化错误 |
| `started_at` | datetime/null | 进入执行时写入 |
| `finished_at` | datetime/null | 终态写入 |

约束：同一个执行者同一时刻最多持有一个 `in_progress` 任务；依赖未全部 `verified` 时不得认领。

### 4.3 SourceDocument

用户上传的不可变原始报告。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `source_id` | string | 主键 |
| `run_id` | string | 外键 |
| `document_type` | enum | MVP 固定为 `annual_report` |
| `file_name` | string | 必填 |
| `media_type` | string | MVP 固定为 `application/pdf` |
| `sha256` | string | 全局去重依据 |
| `storage_uri` | string | 不可变对象地址 |
| `company_name` | string/null | 从文档提取 |
| `security_code` | string/null | 从文档提取 |
| `period_end` | date/null | 从文档提取 |
| `published_at` | datetime/null | 未知不得猜测 |
| `language` | string | MVP 为 `zh-CN` |
| `page_count` | integer | 正整数 |
| `text_extractable` | boolean | MVP 必须为真 |
| `parser_version` | string | 必填 |
| `ingested_at` | datetime | 必填 |

### 4.4 DocumentPage

用于证据定位和解析复现。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `source_id` | string | 联合主键 |
| `page_number` | integer | 从 1 开始，联合主键 |
| `text` | text | 原始页面文本 |
| `text_sha256` | string | 防止静默改写 |
| `bbox_index_uri` | string/null | 表格或文本坐标索引 |

### 4.5 FinancialFact

从报表中提取并经过口径确认的最小财务事实。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `fact_id` | string | 主键 |
| `run_id` | string | 外键 |
| `source_id` | string | 外键 |
| `statement_type` | enum | `balance_sheet/income_statement/cashflow_statement` |
| `concept` | string | 标准概念，例如 `revenue` |
| `label_raw` | string | 报告原始行名 |
| `period_start` | date/null | 时点项为 `null` |
| `period_end` | date | 必填 |
| `period_type` | enum | `instant/duration` |
| `scope` | enum | MVP 必须为 `consolidated` |
| `currency` | string | ISO 4217，MVP 通常为 `CNY` |
| `display_unit` | enum | 必填 |
| `raw_value` | decimal | 报告披露值 |
| `normalized_value` | decimal | 换算到元 |
| `sign_convention` | string | 取值规则版本 |
| `page_number` | integer | 必填 |
| `section` | string | 章节或报表名称 |
| `table_id` | string/null | 表格定位 |
| `row_label` | string | 必填 |
| `column_label` | string | 必填 |
| `bbox` | number[4]/null | 页面坐标 |
| `extraction_method` | enum | `table_parser/text_rule/manual` |
| `confidence` | decimal | `0..1` |
| `validation_status` | enum | `extracted/confirmed/rejected` |

事实唯一粒度：`source_id + concept + period_end + period_type + scope + currency`。出现冲突时不得覆盖，应生成冲突记录并暂停相应计算。

### 4.6 MetricDefinition

版本化的确定性指标定义。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `metric_code` | string | 联合主键 |
| `version` | string | 联合主键 |
| `name_zh` | string | 必填 |
| `formula` | string | 人类可读公式 |
| `input_concepts` | string[] | 必填 |
| `result_type` | enum | `ratio/amount/multiple` |
| `zero_denominator_policy` | enum | MVP 为 `null_with_reason` |
| `missing_input_policy` | enum | MVP 为 `null_with_reason` |
| `rounding_policy` | string | 必填 |

### 4.7 CalculatedMetric

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `metric_id` | string | 主键 |
| `run_id` | string | 外键 |
| `metric_code` | string | 外键到定义 |
| `definition_version` | string | 必填 |
| `period_end` | date | 必填 |
| `input_fact_ids` | string[] | 必填且不可为空 |
| `input_snapshot` | object | 用于复算 |
| `value` | decimal/null | 异常时允许为空 |
| `unit` | string | `ratio/CNY/...` |
| `status` | enum | `calculated/missing_input/zero_denominator/conflict` |
| `reason` | string/null | 非 `calculated` 时必填 |
| `calculator_version` | string | 必填 |
| `calculated_at` | datetime | 必填 |

### 4.8 Claim

报告中的原子陈述，避免整段文本无法验收。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `claim_id` | string | 主键 |
| `run_id` | string | 外键 |
| `claim_type` | enum | `fact/calculation/inference/limitation` |
| `text` | text | 必填 |
| `materiality` | enum | `major/minor` |
| `status` | enum | `draft/supported/unsupported/rejected` |
| `evidence_ids` | string[] | 重大结论不得为空 |
| `created_by` | string | Agent 或规则版本 |

### 4.9 Evidence

连接结论与可验证对象。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `evidence_id` | string | 主键 |
| `claim_id` | string | 外键 |
| `evidence_type` | enum | `source_locator/fact/metric/rule` |
| `source_id` | string/null | 文档证据必填 |
| `page_number` | integer/null | 文档证据必填 |
| `locator` | object/null | 章节、表格、行、列、bbox |
| `fact_id` | string/null | 事实证据使用 |
| `metric_id` | string/null | 计算证据使用 |
| `rule_id` | string/null | 风险规则使用 |
| `excerpt` | string/null | 仅保存必要短摘录 |
| `supports` | enum | `supports/contradicts/qualifies` |

完整性约束：每条 Evidence 至少且只能指向一个主要证据对象；引用必须落到原始来源或可复算指标，不能只引用另一段模型文本。

### 4.10 RiskFinding

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `risk_id` | string | 主键 |
| `run_id` | string | 外键 |
| `risk_code` | string | 版本化规则代码 |
| `category` | enum | `profitability/cashflow/solvency/working_capital/data_quality` |
| `severity` | enum | `critical/high/medium/low` |
| `title` | string | 必填 |
| `description` | text | 必填 |
| `claim_ids` | string[] | 不可为空 |
| `status` | enum | `open/qualified/dismissed` |
| `limitations` | string[] | 可为空 |

### 4.11 Report

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `report_id` | string | 主键 |
| `run_id` | string | 外键 |
| `version` | integer | 从 1 开始 |
| `status` | enum | `draft/candidate/verified/superseded` |
| `schema_version` | string | 必填 |
| `content` | object | 结构化报告 |
| `claim_ids` | string[] | 报告内全部原子结论 |
| `generated_by` | string | 模型与提示版本 |
| `created_at` | datetime | 必填 |

### 4.12 Evaluation

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `evaluation_id` | string | 主键 |
| `run_id` | string | 外键 |
| `report_id` | string | 外键 |
| `evaluator_version` | string | 必填 |
| `status` | enum | `passed/failed/error` |
| `checks` | object[] | 每项含 code、result、evidence、severity |
| `blocking_reasons` | object[] | 失败时不可为空 |
| `created_at` | datetime | 必填 |

Evaluator 不得调用业务工具；它只读取已经持久化的事实、指标、证据、报告和运行信号。

### 4.13 Approval

记录用户对冲突口径、身份修正或敏感导出的决定。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `approval_id` | string | 主键 |
| `run_id` | string | 外键 |
| `request_type` | enum | `identity/metric_scope/sensitive_export` |
| `request_payload` | object | 必填 |
| `status` | enum | `pending/approved/rejected/expired` |
| `decided_by` | string/null | 决定后必填 |
| `decided_at` | datetime/null | 决定后必填 |

### 4.14 AuditEvent 与 WorkflowCheckpoint

`AuditEvent` 保存不可变事件：节点进入/退出、工具请求、权限结果、状态迁移、人工决定和评测结果。F002
最小字段为 `event_id`、`run_id`、`trace_id`、`node`、`event_type`、`status`、`payload` 和
`created_at`。

`WorkflowCheckpoint` 保存 LangGraph 恢复数据：`run_id`、`thread_id`、`checkpoint_id`、`node`、
`state_version`、`state_uri`、`state_data`、`created_at`。`state_data` 只保存控制状态和业务实体引用；
Checkpoint 不代替业务表，业务真值仍写入对应实体。

## 5. 数据质量规则

### 5.1 完整性

- 所有事实必须具有来源、页码、期间、币种、单位、口径和原始值。
- 所有计算必须具有指标版本和输入事实 ID。
- 所有重大 Claim 必须至少有一个 Evidence。

### 5.2 唯一性

- `SourceDocument.sha256` 防止重复文件。
- `AnalysisRun.user_id + idempotency_key` 唯一。
- `FinancialFact` 按既定事实粒度唯一；冲突不得静默去重。

### 5.3 有效性

- 报告期不得晚于 `as_of`。
- `confidence` 必须位于 `0..1`。
- 时点项不得设置 `period_start`；期间项必须设置。
- 比率的输入和输出单位必须匹配指标定义。

### 5.4 一致性与勾稽

- 资产总额应在披露单位容差内等于负债合计加所有者权益合计。
- 毛利润应在容差内等于营业收入减营业成本。
- 现金流量表期末现金应与资产负债表相关口径核对；口径不同必须记录说明。
- 同一事实在摘要和正式财务报表冲突时，以经审计财务报表为主，并记录冲突。

### 5.5 时效性与防时间穿越

- 任何来源的 `published_at` 晚于运行 `as_of` 时不得进入分析。
- 后补数据必须创建新版本，不得修改旧运行结果。

## 6. 黄金数据格式

黄金用例存放在 `tests/golden/`：

```text
tests/golden/
├── README.md
├── manifest.json
└── cases/<case_id>/
    ├── source.md
    └── expected.json
```

`source.md` 是可版本化的合成财报片段；`expected.json` 保存人工确认的事实、指标、风险和证据定位。真实 PDF 进入黄金集前必须完成双人复核、来源授权检查和哈希登记。
