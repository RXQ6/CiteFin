# F004 真实中文年报样本与复核安排

## 目的与冻结边界

本清单用于建立 F004“三张财务报表识别”的真实中文年报复核集，不启动 F005 字段标准化、指标计算或报告生成。样本必须满足：A 股非金融类上市公司、中文可检索 PDF、单一公司 2024 年年度报告全文、包含合并财务报表或能明确判定其缺失/歧义。

公开披露链接只代表候选来源，不代表文件已经进入黄金集。进入黄金集前必须实际取得文件、记录 SHA-256、页数、可检索性、来源授权/使用依据，并完成双人独立复核。

## 候选样本登记（2026-09-06）

以下链接均指向巨潮资讯网 `static.cninfo.com.cn` 的公开披露文件。`candidate_unverified` 表示尚未在项目工作区完成下载、哈希登记和人工核验；不应据此计算准确率。

| # | 公司 | 代码 | 2024 年报告全文候选 | 初始状态 | SHA-256 / 页数 |
|---:|---|---|---|---|---|
| 1 | 宁德时代新能源科技股份有限公司 | 300750 | https://static.cninfo.com.cn/finalpage/2025-03-15/1222806982.PDF | candidate_unverified | 待登记 |
| 2 | 比亚迪股份有限公司 | 002594 | https://static.cninfo.com.cn/finalpage/2025-03-25/1222881496.PDF | candidate_unverified | 待登记 |
| 3 | 立讯精密工业股份有限公司 | 002475 | https://static.cninfo.com.cn/finalpage/2025-04-26/1223326862.PDF | candidate_unverified | 待登记 |
| 4 | 珠海格力电器股份有限公司 | 000651 | https://static.cninfo.com.cn/finalpage/2025-04-28/1223330631.PDF | candidate_unverified | 待登记 |
| 5 | 隆基绿能科技股份有限公司 | 601012 | https://static.cninfo.com.cn/finalpage/2025-04-30/1223421477.PDF | candidate_unverified | 待登记 |
| 6 | 内蒙古伊利实业集团股份有限公司 | 600887 | https://static.cninfo.com.cn/finalpage/2025-04-30/1223421123.PDF | candidate_unverified | 待登记 |
| 7 | 福耀玻璃工业集团股份有限公司 | 600660 | https://static.cninfo.com.cn/finalpage/2025-03-18/1222834950.PDF | candidate_unverified | 待登记 |
| 8 | 天润工业技术股份有限公司 | 002283 | https://static.cninfo.com.cn/finalpage/2025-03-28/1222940333.pdf | candidate_unverified | 待登记 |
| 9 | 三一重工股份有限公司 | 600031 | https://static.cninfo.com.cn/finalpage/2025-04-18/1223129214.PDF | candidate_unverified | 待登记 |
| 10 | 广州珠江钢琴集团股份有限公司 | 002678 | https://static.cninfo.com.cn/finalpage/2025-03-28/1222928245.PDF | candidate_unverified | 待登记 |

选样覆盖高并购/多主体、制造业、多页审计报告、不同交易所和不同披露时间，便于暴露页眉、跨页表格、母公司/合并并列和报告期标记差异。若任一候选实际为摘要、董事会公告、扫描件或非全文，应标记 `rejected_wrong_document` 并以同公司官方全文替换，不能降级使用摘要。

## 文件准入与登记字段

收集人对每个 PDF 建立不可变登记：

- `sample_id`、公司全称、A 股代码、行业排除检查、报告年度和披露日期；
- 原始文件名、官方来源 URL、取得时间、授权/使用依据；
- 文件字节数、SHA-256、页数、媒体类型、是否加密、可检索文本检查结果；
- 解析器版本和 F003 产物引用；
- 三张报表的 A/B 复核记录、冲突记录、裁决记录和最终状态。

未经登记的文件不进入 F004 评测；文件内容变化时必须生成新的 `sample_id`，不能覆盖旧哈希。

## 双人独立复核流程

1. **收集与冻结**：收集人下载官方全文，计算 SHA-256，完成准入检查；只把哈希固定的文件交给 Reviewer A/B。
2. **独立标注**：A、B 在互不查看对方标签的情况下，对每份报告的三类目标各自填写：是否存在、标题原文、合并/母公司/未明口径、报告期、起止页、表格候选 bbox、页文本哈希、缺失或歧义原因。
3. **自动比对**：按 `sample_id + statement_type` 比对 A/B。完全一致才进入 `agreed`；任何页码、标题、期间、口径或缺失原因不一致均进入 `conflict`。
4. **裁决**：裁决人只查看原 PDF、F003 页级文本和坐标证据，不参考模型猜测；保留 A 标签、B 标签、裁决理由和最终证据定位。母公司表不能被裁决为合并表；无法消除的歧义保留 `ambiguous/awaiting_user`。
5. **封存**：每个样本在三类目标均有 A/B 记录、冲突已裁决或明确保留为歧义后，才可标记 `reviewed`。只有 `reviewed` 样本可进入准确率统计。

建议分工：Reviewer A 负责初次页级定位，Reviewer B 独立复核同一批样本，Adjudicator 处理冲突；三者不得由同一人兼任同一份样本的全部角色。评测结果按样本和报表类型分别报告，不把“缺失/歧义的正确识别”误算为“成功定位”。

## F004 完成标准（真实集部分）

- 至少 10 份真实报告完成文件准入、哈希登记和双人复核；
- 每份报告的资产负债表、利润表、现金流量表都有独立标签：`located`、`missing` 或 `ambiguous`；
- `located` 必须同时具备页码、标题、报告期、口径和可回溯定位；
- `missing` / `ambiguous` 必须有结构化原因和原始候选证据；
- A/B 冲突率、裁决数、各状态的 precision/recall 或等价逐项一致率可复算；
- 原始 PDF、哈希、标注、裁决和统计结果可追溯；不得据候选 URL 或首次模型输出声明“中文年报准确率”。

当前文档只建立样本与复核安排，不改变 F004 `candidate_complete` 状态，也不提前实现 F005。
