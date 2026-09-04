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

- 合成 Markdown 不能代表真实 PDF 表格解析表现。
- 尚无双人复核的真实年度报告，因此不能计算真实解析准确率。
- 尚未验证报告生成、证据引用正确性、Checkpoint 恢复或 Goal Gate。

## 2026-09-04：F001 项目初始化与健康检查

### 验证范围

- Ruff 规则和格式。
- Python 3.12 严格 mypy 类型检查。
- FastAPI liveness/readiness 集成测试与配置单元测试。
- 90% 最低覆盖率门禁。
- 3 个合成黄金用例复算。
- Docker Compose 配置解析。

### 执行方式

```powershell
.\scripts\dev.ps1 check
docker compose config --quiet
```

Linux 和 CI 的等价入口：

```bash
make verify-feature FEATURE=F001
```

### 结果

```text
Ruff: passed; 12 files formatted
mypy: Success, 5 source files
golden: 3/3 cases passed
pytest: 3 passed
coverage: 100% (required 90%)
docker compose config: passed
```

### 结论

- F001 的本地可执行验收证据全部通过，状态可转移为 `candidate_complete`；`verified` 仍需独立 CI 成功证据。
- `scripts/dev.ps1` 对失败子命令立即退出，避免产生伪成功交接。
- CI 使用相同锁文件和 Make 质量门禁，后续提交可重复验证基线。

### 已知限制

- 未启动完整容器栈；本次只验证 Compose 配置，不代表 PostgreSQL/Redis 运行连接已验证。
- Starlette TestClient 触发上游 AnyIO 别名弃用警告，不影响当前测试结果。

### 独立验证

- 验证者：GitHub Actions `CI` 工作流。
- 被验证 commit：`6e344af47cacbf46d82580e5bbc87118ddff4f39`。
- 结果：`success`。
- 证据：[CI run 33873094637](https://github.com/RXQ6/CiteFin/actions/runs/33873094637)。
- 状态迁移：F001 从 `candidate_complete` 转为 `verified`。

## 2026-09-04：内部能力——分析运行与幂等创建

### 验证范围

- 同一用户与幂等键重复请求返回原 `run_id` 和原始持久化包。
- 相同幂等键在不同用户范围内相互隔离。
- 创建运行时原子写入 AnalysisRun、根 Task、AuditEvent 和初始 WorkflowCheckpoint。
- 非法 A 股证券代码、未来报告期、重复及冲突关注点返回 `422`。
- 未配置数据库时返回具有错误码和修复提示的 `503`。
- UUIDv7 前缀 ID、SQLite 空库迁移、Alembic ORM 零漂移。
- PostgreSQL 17 空库升级和零漂移检查。

### 本地结果

```text
Ruff and format: passed; 24 files
mypy: Success; 14 source files
golden: 3/3 cases passed
pytest: 14 passed
coverage: 94.24% (required 90%)
alembic check: No new upgrade operations detected
```

### 独立 CI 反馈与修复

- 首次运行 [33875453465](https://github.com/RXQ6/CiteFin/actions/runs/33875453465)：PostgreSQL 迁移通过，但 job 级数据库环境变量污染了安全默认值和 SQLite 隔离测试，质量门禁失败。
- 修复：将 PostgreSQL URL 限定在迁移步骤内，使产品测试不继承外部数据库配置。
- 通过运行：[33875648380](https://github.com/RXQ6/CiteFin/actions/runs/33875648380)。
- 被验证 commit：`06306a53a35b9ace095a0231478684d24d938f5c`。
- 结果：PostgreSQL 迁移、Alembic 零漂移和完整 `make check` 全部成功。
- 结论：该能力作为 F002 的内部前置接口通过验证，但不占用产品功能编号。

### 已知限制

- 尚未进行高并发请求压测；并发幂等由数据库唯一约束和 IntegrityError 回读路径保护。
- 尚未接入真实认证，`X-User-ID` 只用于当前接口契约与测试。
- 当前 Checkpoint 是初始恢复边界，不代表后续 LangGraph 节点已经实现。

## 2026-09-04：F002 财报上传与不可变文件存储

### 验证范围

- 可检索 PDF 上传、文件名净化和来源元数据持久化。
- 50 MiB 默认有界读取与超限 `413`。
- 非 PDF、错误扩展名、损坏、加密和图片型 PDF 的稳定错误码。
- 错误用户不能探测或上传到其他用户的分析运行。
- 同一运行重复内容返回原 `source_id`，不新增来源、对象或审计事件。
- 不同运行上传同一内容时保留两个来源记录，但只保存一个物理对象。
- 对象落盘内容与 SHA-256 地址一致，上传产生 `document_uploaded` 审计事件。
- 从 F001 数据库升级到 F002，SQLite 与 PostgreSQL 17 均无 ORM 漂移。
- Compose 配置包含迁移前置服务和对象存储持久卷。

### 本地结果

```text
Ruff and format: passed; 28 files
mypy: Success; 17 source files
golden: 3/3 cases passed
pytest: 23 passed
coverage: 92.20% (required 90%)
alembic upgrade: 20260904_0001 -> 20260904_0002
alembic check: No new upgrade operations detected
docker compose config: passed
```

### 独立验证

- 验证者：GitHub Actions `CI` 工作流，PostgreSQL 17 服务容器。
- 被验证 commit：`ef24f95889b6d30a49f3ee7c8228717f18a72303`。
- 结果：[CI run 33889907495](https://github.com/RXQ6/CiteFin/actions/runs/33889907495) 成功。
- 验证内容：依赖锁定安装、PostgreSQL 全量迁移、Alembic 零漂移及完整 `make check`。
- 状态迁移：F002 从 `in_progress` 转为 `verified`。

### 已知限制

- 测试 PDF 为代码生成的最小文档；真实中文上市公司年报仍需进入人工复核黄金集。
- 可检索文本阈值不能替代公司、期间、年报类型和语言语义确认。
- 本次验证未构建并启动完整 Docker Compose 栈，只验证了 Compose 配置和 CI PostgreSQL 迁移。

## 2026-09-05：F001/F002 权威功能表复核

### 复核范围

- F001–F018 的 ID、名称和依赖与用户确认的产品功能表一致。
- 只有 F001、F002 为 `verified`；F003–F018 均为 `not_started`，WIP=0。
- 项目开发 Feature 编号与金融分析运行时 `Task.feature_id` 分离。
- F001/F002 完整代码门禁、合成黄金数据、迁移和 Compose 配置重新执行。

### 结果

```text
catalog: F001..F018 valid; dependencies valid; verified=F001,F002; in_progress=0
Ruff and format: passed; 29 files
mypy: Success; 17 source files
golden: 3/3 cases passed
pytest: 25 passed
coverage: 92.20% (required 90%)
alembic upgrade: base -> 20260904_0001 -> 20260904_0002
alembic check: No new upgrade operations detected
docker compose config: passed
```

### 执行说明与结论

- 沙箱内首次执行因系统 Python 进程权限被拒绝而中断；使用同一锁定虚拟环境在获准执行上下文中从头重跑后全部通过，不属于代码或测试失败。
- 新增清单契约测试首次被 Ruff 导入排序规则拦截；运行项目格式化入口修复后，完整门禁从头重跑通过。
- F001 和 F002 在当前冻结验收范围内通过；未实现、未启动 F003。
- F002 只保证上传与不可变文件存储，不声明真实中文年报语义解析正确；该能力从 F003 开始验收。

### 独立验证

- 验证者：GitHub Actions `CI` 工作流，PostgreSQL 17 服务容器。
- 被验证 commit：`7315d26088bf80580f083015ced58d3bedf50846`。
- 结果：[CI run 33892520145](https://github.com/RXQ6/CiteFin/actions/runs/33892520145) 成功。
- 验证内容：PostgreSQL 全量迁移、Alembic 零漂移、功能清单契约测试及完整 `make check`。
