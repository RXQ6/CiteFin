# F004 30 目标复核包

## 用途

本复核包用于把 10 份已封存的 2024 年中文 A 股非金融类上市公司年报交给 Reviewer A、Reviewer B 和裁决人。它只提供复核范围、字段和规则，不预填任何机器结论。

## 输入文件

- 样本清单：`data/real_reports/manifest.json`
- 30 行目标队列：`data/real_reports/review_queue.csv`
- 原始 PDF：`data/real_reports/<file>`
- 复核规则：`docs/F004_REAL_REPORT_REVIEW_PLAN.md`

`manifest.json` 中的 SHA-256、页数和官方来源必须先核对。`machine_preannotations.json` 和 `machine_preannotations_after_fix.json` 只能由项目负责人保存，不能发给 Reviewer A/B 作为初始答案。

## 分发方式

1. 将相同的 30 行目标队列分别复制为 Reviewer A 和 Reviewer B 的工作副本。
2. A、B 不互相查看结果，也不查看机器预标注。
3. 裁决人只在 A/B 提交后查看冲突行和原始 PDF。
4. 原始 PDF 使用只读副本；复核副本不得改写文件内容或哈希。

## 每行必填字段

```text
sample_id, security_code, company_name, report_year, statement_type,
status, title_raw, page_start, page_end, scope, period_end,
locator, page_text_sha256, evidence_excerpt, reason_code, reviewer_id, reviewed_at
```

`status` 只能是：

- `located`：找到目标合并报表；
- `missing`：在全文中没有足够证据定位；
- `ambiguous`：存在多个无法消除的候选或口径/期间冲突。

`located` 必须同时填写标题、页码、`consolidated` 口径、报告期和可回溯定位；`missing`/`ambiguous` 必须填写结构化原因和候选证据。

## 比对与裁决

- A/B 的状态、页码、标题、口径、报告期或原因任一不同，都标记为 `conflict`。
- 裁决表至少保留 `reviewer_a_*`、`reviewer_b_*`、`adjudication_status`、`final_status`、`adjudication_reason` 和最终证据定位。
- 不能消除的歧义必须保留为 `ambiguous`，不能为了提高定位率强行选择。

## 完成标准

- 30 个目标都有 A 标签和 B 标签；
- 所有冲突都有裁决或明确保留为歧义；
- 一致率、冲突率、最终状态分布可由队列复算；
- PDF、哈希、标注、裁决和统计结果可追溯；
- 在独立 Goal Gate 通过前，不得声明真实中文年报准确率。

## 交付物

- A/B 两份只读原始标注副本；
- 冲突裁决表；
- 一致率和冲突率统计；
- 更新后的 `review_queue.csv`、`manifest.json` 状态和 `docs/VALIDATION.md` 记录。
