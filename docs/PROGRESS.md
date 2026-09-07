# 项目进度

> 这是跨会话交接的事实来源。每次暂停、交接或结束工作前更新；不要依赖聊天记录保存项目状态。

## 当前状态

- 最后更新：2026-09-07
- 更新人：Codex
- 当前阶段：F001–F003 已验证；F004 处于透明 `provisional` 工程状态，F005–F013 已完成 provisional 工程单元并处于 `candidate_complete`；真实复核和正式 Goal Gate 仍待完成
- 最新本地工程检查点：`e7915e5`（F013 原子实现；F012 检查点为 `a4927b2`）
- F004 candidate 实现已推送并通过独立 CI；F005–F013 为本地 provisional 工程实现，真实年报语义/风险/报告准确率和正式 Goal Gate 仍待完成
- 测试状态：110/110 pytest 通过，覆盖率 91.21%；3/3 合成黄金用例通过；F006 专项 6/6、F007 专项 2/2、F008 专项 26/26、F009 专项 6/6、F010 专项 5/5、F011 专项 4/4、F012 专项 4/4、F013 专项 6/6 通过；迁移升级和 Alembic 零漂移通过
- 质量状态：F004 本地 Ruff、格式检查、严格 mypy、SQLite 升级、Alembic 零漂移和 PostgreSQL 17 独立 CI 均通过；F013 唯一 Goal Gate、verified 状态防护、失败修复路由、审计决策和幂等 API 已通过本地门禁；真实中文年报准确率尚未验证
- 本次变更摘要：F003 已实现页级文本与哈希、不可变坐标索引、表格候选、结构化失败、幂等重放、用户隔离与页数上限；F004 已实现确定性三表识别、报告期/合并口径判定、结构化缺失与人工确认边界；F006 已实现 15 项 Decimal 指标、结果快照和计算 API；F007 已实现 Claim/Evidence 关系和来源定位校验；F008 已实现类型化工作流状态、确定性节点路由、状态转移审计和状态边界校验；F009 已实现确定性计算/限制/推断 Claim、metric/rule Evidence 自动挂接和幂等分析 API；F010 已实现 RiskFinding、版本化风险规则、事实与规则/指标 Evidence、数据质量降级和幂等风险 API；F011 已实现 Report、financial-report-v1 Schema、证据映射、只读组装和幂等报告 API；F012 已实现独立 Evaluation、结构化检查/修复指令、输入快照和幂等评测 API；F013 已实现唯一 Goal Gate、GoalGateDecision、verified 状态保护和失败修复路由 API。
- 本次恢复验证：重建指向失效系统 Python 的 `.venv` 后，项目内可写临时目录下 25/25 pytest 通过，覆盖率 92.20%；未启动 F003。

## 已完成

- [x] 明确项目定位：金融研究、数据分析和风险提示的辅助决策 Agent。
- [x] 建立根目录 `AGENTS.md`，定义全局约束与文档导航。
- [x] 建立本进度文件，作为跨会话恢复入口。
- [x] 建立 `docs/DECISIONS.md`，记录关键设计选择及其理由。
- [x] 明确每次会话的 Make 初始化、验证、状态更新与原子 Git 提交流程。
- [x] 冻结首期场景：用户上传 A 股非金融类公司的中文可检索年度报告。
- [x] 建立 `docs/PRODUCT_SCOPE.md`，定义输入、输出、非目标和完成条件。
- [x] 建立 `docs/DATA_MODEL.md`，定义事实、指标、Claim、Evidence、报告和评测模型。
- [x] 建立 `docs/WORKFLOW.md`，定义 LangGraph 节点、状态、Hooks、重试、恢复和 Goal Gate。
- [x] 建立 `FEATURES.json`，包含 18 个有依赖和验收证据的 MVP 功能。
- [x] 建立 3 个合成黄金用例，覆盖正常、风险和零分母/单位换算边界。
- [x] 建立 `docs/VALIDATION.md`，记录规格和黄金数据验证结果。
- [x] 初始化 Python 3.12、uv、FastAPI、pytest、Ruff、mypy 和 GitHub Actions。
- [x] 建立 PostgreSQL、Redis 与 API 的 Docker Compose 基线。
- [x] 建立 `/api/v1/health/live` 和 `/api/v1/health/ready` 健康检查。
- [x] 完成 F001 项目初始化与健康检查的本地质量门禁。
- [x] GitHub Actions 独立验证实现 commit `6e344af`，F001 转移为 `verified`。
- [x] 初始化 Git 仓库并推送至 `RXQ6/CiteFin` 的 `main` 分支。
- [x] 建立 SQLAlchemy 2 与 Alembic 数据库基础设施。
- [x] 实现 `POST /api/v1/analysis-runs` 和用户范围幂等语义。
- [x] 在同一事务内创建 AnalysisRun、根 Task、AuditEvent 和初始 WorkflowCheckpoint。
- [x] 拒绝非法 A 股代码、未来报告期、重复或冲突的分析关注点。
- [x] GitHub Actions 在 PostgreSQL 17 上验证内部分析运行初始化与零漂移。
- [x] 纠正功能编号：F001 为项目初始化与健康检查，F002 为财报上传与文件存储，内部运行任务不占产品编号。
- [x] 实现 `POST /api/v1/analysis-runs/{run_id}/documents` multipart 上传接口。
- [x] 拒绝超限、非 PDF、损坏、加密和图片型 PDF，并返回稳定错误码。
- [x] 使用 SHA-256 内容寻址对象实现跨运行物理去重，同时保留运行内来源归属。
- [x] 保存文件名、媒体类型、哈希、存储 URI、页数、语言、解析器版本和审计事件。
- [x] Compose 增加迁移前置服务和不可变对象持久卷。
- [x] GitHub Actions 在 PostgreSQL 17 上验证 F002 迁移和完整门禁，F002 转移为 `verified`。
- [x] 实现 F003 `DocumentPage` 模型、迁移及页码从 1 开始的确定性 PDF 解析。
- [x] 保存逐页文本 SHA-256、解析器版本和带哈希的不可变坐标 JSON。
- [x] 保存文本块、表格候选 bbox、结构化失败页和 `document_parsed` 审计事件。
- [x] 验证解析幂等、用户归属、2000 页默认上限、对象完整性和既有能力回归。
- [x] 实现 F004 三表识别记录、迁移、`statement_extract` 接口和版本化确定性匹配规则。
- [x] 保留母公司、未明确合并口径、多个候选和报告期冲突，不静默选择并返回人工确认或明确缺失原因。
- [x] 通过 F004 专项场景、全量回归、格式、类型、黄金数据和 Alembic 零漂移验证；等待独立 CI 验证。
- [x] GitHub Actions 独立验证 F004：CI run 34015101188 成功。
- [x] 建立 10 份官方年报候选及 F004 双人独立复核、冲突裁决和哈希封存计划。
- [x] 取得 10 份官方 2024 年年报 PDF，登记页数、字节数和 SHA-256。
- [x] 对 10 份真实报告执行 F004 机器预标注并保留结果；未将其作为黄金真值。
- [x] 修正报告期范围误判、重复候选排序和五年业绩摘要误选，并完成 10 份报告的完整 API 回放：30/30 目标定位为合并口径 2024-12-31。
- [x] 将修正后的 F004 推送到 GitHub，并通过独立 CI run `34018998550`。
- [x] 制作 F004 30 个目标的盲审复核包，明确 A/B 字段、裁决字段和禁止使用机器预标注的规则。
- [x] 在隔离分支完成并合入主线的 F005 第一工作单元：FinancialFact、Decimal 单位换算、确定性标签映射、冲突保留 API 和迁移。
- [x] 增加 `provisional` 工程推进状态，保持 `verified` 仍由 Goal Gate 控制。
- [x] 为 F005 增加可执行专项验证器，覆盖专项测试、全量迁移升级和 Alembic 零漂移。
- [x] F005 通过全量质量门禁和专项验证，状态转为本地 `candidate_complete`；未声明真实中文年报准确率。
- [x] 校验 F004 10 份封存 PDF 的哈希/页数，并生成不含机器预标注的 Reviewer A/B 空白盲审副本。
- [x] 在明确 provisional 工程边界后实现 F006 15 项 Decimal 指标、结果持久化、输入快照、结构化缺失/零分母状态和计算 API。
- [x] 实现 F007 Claim/Evidence 模型、来源页/事实/指标/规则证据链接、用户隔离和最小写入 API。
- [x] 实现 F008 类型化工作流状态、节点路由、合法转移校验、状态版本递增和 AuditEvent 边界，并通过全量质量门禁。
- [x] 实现 F009 确定性财务分析 Claim、限制与推断规则、Evidence 自动挂接、用户隔离和幂等 API，并通过全量质量门禁。
- [x] 实现 F010 确定性风险规则、RiskFinding 持久化、事实与规则/指标 Evidence、数据不足降级、用户隔离和幂等 API，并通过全量质量门禁。
- [x] 实现 F011 版本化候选报告、事实/计算/推断/风险/限制分区、Evidence 映射、只读组装、用户隔离和幂等 API，并通过全量质量门禁。

## 进行中

- F004 双人复核与正式 Goal Gate 外部验收尚未完成；F005–F013 仍是 provisional 工程证据，真实年报事实/风险/报告准确率和真实证据覆盖率不得声明；F013 完成后等待下一项明确开发指令。

## 已知问题

- 当前黄金集仅为合成数据，不能用于声明真实 PDF 解析准确率。
- 已取得 10 个真实年报 PDF 并完成 SHA-256/页数/可检索性登记；机器回放 30/30 定位成功；公开披露使用依据、双人复核者和裁决人仍待确认，机器结果不能替代人工真值。
- `docs/architecture.md` 等非 MVP 必需专题文档仍待建立。
- 当前 readiness 只检查依赖配置是否存在，后续再增加真实连接探测。
- Windows 环境没有全局 `make`；使用等价入口 `scripts/dev.ps1`，CI 继续验证 Make 入口。
- `X-User-ID` 只是内部运行初始化能力的临时身份边界，生产使用前必须替换为认证主体，不能信任任意客户端值。
- 当前只创建 LangGraph 初始 Checkpoint 记录，尚未执行后续工作流节点。
- F008 当前实现验证的是类型化状态、确定性路由和审计边界，不是完整 LangGraph 执行器；正式 `verified` 仍需独立 Goal Gate。
- F009 当前只读取 `CalculatedMetric`，以确定性规则写入 Claim/Evidence；尚未实现独立 Evaluator、风险实体、报告生成或真实年报语义准确率验证。
- F010 当前只读取已持久化 `CalculatedMetric` 和 `FinancialFact`，以版本化确定性规则写入 `RiskFinding`/Claim/Evidence；尚未实现独立 Evaluator、报告生成或真实年报风险准确率验证。
- F011 当前只读组装已持久化实体并生成 `candidate` 报告；尚未实现独立 Evaluator、Goal Gate、报告发布或真实年报报告质量验证。
- F012 当前使用确定性规则评测持久化候选报告；尚未实现 Goal Gate、修订执行器、真实年报独立评测或报告质量准确率验证。
- F013 当前使用确定性规则执行 Goal Gate；尚未完成真实年报独立证据、人工复核和正式生产验收。
- AuditEvent 通过服务层保持追加写；数据库级禁止 UPDATE/DELETE 的权限策略尚未建立。
- 当前可检索性闸门基于文本字符阈值；尚未确认文件确为中文正式年报、目标公司和目标报告期。
- 当前对象存储适配器为本地持久卷，尚未实现 S3/MinIO 等生产对象存储后端。
- 文件写入成功但数据库事务最终失败时可能留下无引用对象，后续运维需要安全的孤儿对象清理流程。
- F003 的 bbox 来自 PDF 文本矩阵并使用版本化宽度估算；复杂旋转、异常字体编码和跨页表格仍需真实年报验证。
- F003 的表格区域是确定性候选，不代表三张财务报表或合并口径已被识别；这些语义属于 F004。

## 下一步

完成 F013 的文档与 Git 检查点后，等待项目负责人选择下一项功能；保留 F004–F013 的正式 Goal Gate 外部证据阻塞和真实年报准确率禁令，不启动 F014。

## 恢复提示

- 恢复工作时，先阅读本文件，再阅读 `docs/DECISIONS.md` 与 `docs/VALIDATION.md`（如已存在）。
- 运行项目前确认 Git 状态；不要把未验证的聊天结论当作项目事实。
- 完成一个可验证的工作单元后，先更新本文件，再交接给下一位 Agent。
