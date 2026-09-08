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

可用以下命令校验封存文件并生成两份空白盲审副本：

```powershell
.\scripts\dev.ps1 prepare-f004-review
```

输出位于 `artifacts/f004_review/`，包含 `reviewer_a.csv`、`reviewer_b.csv`、`adjudication.csv` 和交接说明。该命令不会读取或复制机器预标注结论。

1. 将相同的 30 行目标队列分别复制为 Reviewer A 和 Reviewer B 的工作副本。
2. A、B 不互相查看结果，也不查看机器预标注。
3. 裁决人只在 A/B 提交后查看冲突行和原始 PDF。
4. 原始 PDF 使用只读副本；复核副本不得改写文件内容或哈希。
5. Reviewer A、Reviewer B 和裁决人分别使用不同的非识别性 `human-*` 代码；不得在复核包中记录姓名、联系方式或其他个人信息。

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

`located` 必须同时填写标题、页码、`consolidated` 口径、报告期、可回溯定位、页文本 SHA-256 和证据摘录；`missing`/`ambiguous` 必须填写结构化原因和候选证据。`reviewed_at` 必须是带明确 UTC 偏移量的 ISO-8601 时间。

## 比对与裁决

- A/B 的状态、页码、标题、口径、报告期、定位、页文本哈希、证据摘录或原因任一不同，都标记为 `conflict`。
- A/B 原始提交分别保留；`adjudication.csv` 只填写冲突行，并记录 `adjudication_status`、最终字段、裁决理由、裁决人代码和裁决时间。
- 不能消除的歧义必须保留为 `ambiguous`，不能为了提高定位率强行选择。

收到 A/B 和裁决结果后执行：

```powershell
.\scripts\dev.ps1 validate-f004-review
```

验证器会重新核对 PDF 字节数、页数、文件 SHA-256、提交身份、角色隔离、页范围和页文本 SHA-256，并将输入哈希、一致率、冲突率、裁决数及机器逐项得分写入 `artifacts/f004_review/results/review-validation.json`。若来源使用依据仍为 pending、提交不完整或证据不一致，结果不会进入可评分状态。

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
