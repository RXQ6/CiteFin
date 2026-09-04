# 项目进度

> 这是跨会话交接的事实来源。每次暂停、交接或结束工作前更新；不要依赖聊天记录保存项目状态。

## 当前状态

- 最后更新：2026-09-04
- 更新人：Codex
- 当前阶段：F001 本地门禁通过，等待独立 CI 验证后进入 F002
- 最新实现 commit：`6e344af`（feat: bootstrap reproducible FastAPI baseline）
- 测试状态：3/3 pytest 通过，分支覆盖率 100%；3/3 合成黄金用例通过
- 质量状态：Ruff、格式检查、严格 mypy、Docker Compose 配置检查均通过
- 本次变更摘要：完成 Python/FastAPI 工程骨架、统一 harness、健康检查、容器依赖和 CI，并推送至 GitHub。

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
- [x] 完成 F001 本地质量门禁并将状态转移为 `candidate_complete`。
- [x] 初始化 Git 仓库并推送至 `RXQ6/CiteFin` 的 `main` 分支。

## 进行中

- [ ] 对 MVP 规格进行人工确认并冻结版本 `v1.0`。
- [ ] 等待 GitHub Actions 独立验证 F001，通过后转移为 `verified`。
- [ ] 实现 F002：分析运行、幂等创建、初始审计事件和 Checkpoint。
- [ ] 选择并双人复核首批真实年度报告黄金用例。

## 已知问题

- 当前黄金集仅为合成数据，不能用于声明真实 PDF 解析准确率。
- 尚未确定真实年度报告的选样公司、来源 URL、授权记录和双人复核者。
- `docs/architecture.md` 等非 MVP 必需专题文档仍待建立。
- 当前 readiness 只检查依赖配置是否存在，F002 后再增加真实连接探测。
- Windows 环境没有全局 `make`；使用等价入口 `scripts/dev.ps1`，CI 继续验证 Make 入口。

## 下一步

1. 取得 F001 的 GitHub Actions 独立成功证据并转移为 `verified`。
2. 将 F002 从 `not_started` 转为 `in_progress`，一次只实现这一项功能。
3. 建立 AnalysisRun、AuditEvent 和 Checkpoint 的数据库模型与迁移。
4. 实现带用户级幂等键的运行创建接口及契约测试。

## 恢复提示

- 恢复工作时，先阅读本文件，再阅读 `docs/DECISIONS.md` 与 `docs/VALIDATION.md`（如已存在）。
- 运行项目前确认 Git 状态；不要把未验证的聊天结论当作项目事实。
- 完成一个可验证的工作单元后，先更新本文件，再交接给下一位 Agent。
