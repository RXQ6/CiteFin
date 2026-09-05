# 项目进度

> 这是跨会话交接的事实来源。每次暂停、交接或结束工作前更新；不要依赖聊天记录保存项目状态。

## 当前状态

- 最后更新：2026-09-06
- 更新人：Codex
- 当前阶段：F001、F002 已验证；用户已明确授权，F003“PDF文本与表格解析”正在实现
- 最新已独立验证实现 commit：`7315d26`（fix: align F001-F018 with authoritative product plan）
- 测试状态：25/25 pytest 通过，覆盖率 92.20%；3/3 合成黄金用例通过
- 质量状态：Ruff、格式检查、严格 mypy、SQLite 升级、PostgreSQL 17 升级和 Alembic 零漂移检查均通过
- 本次变更摘要：按金融 Agent 冻结场景启动 F003，边界为中文可检索 A 股非金融类合并年报的确定性页级文本、表格坐标、哈希和失败留痕。
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

## 进行中

- F003“PDF文本与表格解析”，owner=`codex`，WIP=1。
- 完成标准：原始页码从 1 开始；逐页保存文本哈希与解析器版本；表格坐标可供后续证据定位；失败页保留结构化错误。

## 已知问题

- 当前黄金集仅为合成数据，不能用于声明真实 PDF 解析准确率。
- 尚未确定真实年度报告的选样公司、来源 URL、授权记录和双人复核者。
- `docs/architecture.md` 等非 MVP 必需专题文档仍待建立。
- 当前 readiness 只检查依赖配置是否存在，后续再增加真实连接探测。
- Windows 环境没有全局 `make`；使用等价入口 `scripts/dev.ps1`，CI 继续验证 Make 入口。
- `X-User-ID` 只是内部运行初始化能力的临时身份边界，生产使用前必须替换为认证主体，不能信任任意客户端值。
- 当前只创建 LangGraph 初始 Checkpoint 记录，尚未执行后续工作流节点。
- AuditEvent 通过服务层保持追加写；数据库级禁止 UPDATE/DELETE 的权限策略尚未建立。
- 当前可检索性闸门基于文本字符阈值；尚未确认文件确为中文正式年报、目标公司和目标报告期。
- 当前对象存储适配器为本地持久卷，尚未实现 S3/MinIO 等生产对象存储后端。
- 文件写入成功但数据库事务最终失败时可能留下无引用对象，后续运维需要安全的孤儿对象清理流程。

## 下一步

实现 F003 的数据库模型、迁移、确定性解析服务和 API 契约测试；完成本地门禁后转为 `candidate_complete`，等待独立验证，不提前实现 F004。

## 恢复提示

- 恢复工作时，先阅读本文件，再阅读 `docs/DECISIONS.md` 与 `docs/VALIDATION.md`（如已存在）。
- 运行项目前确认 Git 状态；不要把未验证的聊天结论当作项目事实。
- 完成一个可验证的工作单元后，先更新本文件，再交接给下一位 Agent。
