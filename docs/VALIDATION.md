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

## 2026-09-05：会话初始化验证

### 验证范围

- 完整恢复项目状态并检查 Git 基线。
- 使用 Windows 等价入口执行锁定依赖初始化与 pytest 基线。
- 确认本次恢复没有启动或修改 F003。

### 环境问题与处理

- 首次 `scripts/dev.ps1 setup` 成功检查 73 个包，但原 `.venv` 指向已不存在的系统 Python 3.12.5，导致 pytest 进程无法创建并返回 101。
- 使用 Codex 随附的 CPython 3.12.14 重建 `.venv`；清华镜像对锁定的 `pathspec==1.1.1` 返回 403，因此从未修改的 `uv.lock` 导出精确版本清单，并通过官方 PyPI 补齐本地依赖。
- 标准测试在受限环境的系统临时目录遇到 `WinError 5`；将 pytest `--basetemp` 定向到项目内全新可写目录并关闭不可写的缓存插件后，从头重跑相同测试集。

### 最终结果

```text
setup: Checked 73 packages
pytest: 25 passed, 1 warning
coverage: 92.20% (required 90%)
```

### 结论与已知限制

- F001/F002 当前代码基线通过初始化测试；失败过程均由本机解释器、镜像或沙箱临时目录造成，未发现测试断言失败。
- Starlette TestClient 仍有 AnyIO 别名弃用警告，不影响本次结果。
- `FEATURES.json` 未修改：F001、F002 保持 `verified`，F003 保持 `not_started`。

## 2026-09-06：F003 启动基线

### 验证范围

- F002 已为 `verified`，满足 F003 唯一前置依赖。
- Windows 锁定环境初始化与现有完整 pytest 基线。
- F003 场景边界与产品范围、数据模型和 `document_parse` 节点契约一致。

### 结果

```text
setup: Checked 73 packages
pytest: 25 passed, 1 warning
coverage: 92.20% (required 90%)
```

### 结论

- 基线通过，可将 F003 转为 `in_progress`，WIP=1。
- F003 只实现页级文本、页级哈希、表格/文本坐标索引和结构化失败留痕；不提前实现 F004 三表识别。

## 2026-09-06：F003 PDF文本与表格解析

### 验证范围

- 两页 PDF 按原始顺序持久化为从 1 开始的 `DocumentPage`。
- 每页保存原始提取文本、SHA-256、pypdf 与 bbox 算法版本。
- 规范 JSON 坐标索引保存页面尺寸、坐标系、文本块 bbox 和表格候选 bbox，并作为不可变对象登记 URI 与哈希。
- 同一来源重复解析返回原页面，不新增页面或解析审计事件。
- 其他用户无法探测或解析不属于自己的来源文件。
- 默认 2000 页解析上限返回稳定错误码，避免异常 PDF 造成无界工作。
- 单页提取失败时保留页码、空文本哈希和 `PARSER_PAGE_EXTRACTION_FAILED`，其他页仍持久化。
- 源 PDF 读取和派生 JSON 重用均校验内容地址完整性。
- SQLite 从空库升级到 F003，并与 ORM 元数据零漂移。
- F001/F002 接口、功能清单、黄金数据和 Compose 配置回归。

### 本地结果

```text
Ruff and format: passed; 33 files
mypy: Success; 18 source files
golden: 3/3 cases passed
pytest: 32 passed, 1 warning
coverage: 91.54% (required 90%)
alembic upgrade: base -> 20260904_0001 -> 20260904_0002 -> 20260906_0003
alembic check: No new upgrade operations detected
docker compose config: passed
```

### 结论

- F003 四项验收条件均有机器可执行证据，本地状态可转为 `candidate_complete`。
- 实现未调用 LLM、外部网络或 OCR，未提前执行 F004 的三表语义识别。
- 本地 Docker 命令因沙箱无法读取用户级 Docker 配置而输出警告，但 Compose 配置解析返回 0。

### 已知限制与待独立验证

- 测试使用代码生成的可检索两页 PDF，只证明页级契约和定位结构，不证明真实中文年报解析准确率。
- bbox 宽度是版本化估算；复杂字体、旋转页和跨页表格需要纳入双人复核的真实 PDF 黄金集。
- 表格区域是候选定位，三张合并报表的识别准确性从 F004 开始验收。
- PostgreSQL 17 全量迁移和完整门禁已由 GitHub Actions 独立验证。

### 独立验证

- 验证者：GitHub Actions `CI` 工作流，PostgreSQL 17 服务容器。
- 被验证 commit：`8a7f497fd5dfba3ba5363299ee46d686af1e36d4`。
- 结果：[CI run 33978087346](https://github.com/RXQ6/CiteFin/actions/runs/33978087346) 成功。
- 验证内容：锁定依赖安装、PostgreSQL 全量迁移、Alembic 零漂移及完整 `make check`。
- 状态迁移：F003 从 `candidate_complete` 转为 `verified`。
- 状态记录提交 `3cc70c1` 的最终回归 [CI run 33978374798](https://github.com/RXQ6/CiteFin/actions/runs/33978374798) 同样成功。

## 2026-09-06：F004 三张财务报表识别

### 验证范围

- 从 F003 已持久化的页文本和不可变坐标索引中确定性识别合并资产负债表、利润表和现金流量表。
- 识别结果保存标题、报告期、页码、表格候选定位、页文本哈希和坐标索引哈希。
- 仅有母公司表时返回明确缺失原因，不将其冒充为合并报表。
- 合并口径未明确、多个合并候选或报告期冲突时保留全部候选并返回人工确认状态。
- 同一来源重复识别幂等，其他用户不能读取结果；未完成 F003 解析时拒绝识别。
- SQLite 从空库升级至 F004，ORM 元数据无漂移。
- F001–F003 接口、功能清单、黄金数据和既有测试回归。

### 执行方式

Windows 使用锁定虚拟环境和项目外可写 pytest 临时目录执行：

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe tests/golden/validate.py
.\.venv\Scripts\python.exe -m pytest --basetemp <writable-temp> -p no:cacheprovider
$env:CITEFIN_DATABASE_URL = "sqlite+pysqlite:///.../f004-migration.db"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

### 结果

```text
setup: Checked 73 packages
Ruff: passed
format: 36 files already formatted
mypy: Success, 19 source files
golden: 3/3 cases passed
pytest: 41 passed, 1 warning
coverage: 91.08% (required 90%)
alembic upgrade: base -> 20260904_0001 -> 20260904_0002 -> 20260906_0003 -> 20260906_0004
alembic check: No new upgrade operations detected
```

### 结论与限制

- F004 四项验收条件均有本地机器可执行证据，状态可转为 `candidate_complete`；`verified` 仍需独立验证。
- 识别逻辑不调用 LLM、OCR、外部网络或 F005 字段标准化/指标计算。
- 当前专项测试使用合成可检索 PDF 和中英文标题，尚不能声明真实中文年度报告识别准确率。
- 真实报告进入准确率黄金集前仍需来源授权、哈希登记和双人复核。

## 2026-09-06：F004 独立 CI 验证与真实样本计划

### 独立验证

- 验证者：GitHub Actions `CI` 工作流，PostgreSQL 17 服务容器。
- 被验证内容树：与本地 F004 提交相同（F004 实现内容未被修改）。
- 远端提交：`f831b4d99100341608f7cd920591ead283a07051`。
- 结果：`success`；PostgreSQL 全量迁移、Alembic 零漂移和完整 `make check` 通过。
- 证据：[CI run 34015101188](https://github.com/RXQ6/CiteFin/actions/runs/34015101188)。

### 真实样本安排

- 已建立 `docs/F004_REAL_REPORT_REVIEW_PLAN.md`，列出 10 份巨潮资讯网 2024 年年报全文候选及准入、双人独立复核、冲突裁决和封存标准。
- 候选 URL 尚不等于已取得的项目输入；在 PDF 实际取得、授权/使用依据、SHA-256、页数和 A/B 标注完成前，不计算真实准确率。
- 当前 F004 仍为 `candidate_complete`；独立 CI 证明的是工程质量门禁，不等同于真实中文年报语义准确率或 Goal Gate `verified`。

## 2026-09-06：真实年报样本取得与 F004 机器预标注试运行

### 样本取得与完整性检查

- 从已登记的巨潮资讯网公开披露地址取得 10 份 2024 年 A 股非金融公司年报全文，保存于 `data/real_reports/`。
- 10/10 文件为 PDF；共 2,445 页，2,445 页均通过 pypdf 非空文本提取检查。
- 每个文件已登记字节数、页数、SHA-256、来源 URL 和 `awaiting_independent_review` 状态；完整清单见 `data/real_reports/manifest.json`。
- 30 个三表复核目标已建立队列，见 `data/real_reports/review_queue.csv`。

### 机器预标注

- 使用 `statement-identification-v1` 对 10 份真实报告执行 F003 解析和 F004 识别；结果保存在 `data/real_reports/machine_preannotations.json`。
- 10/10 份报告的总体状态均为 `awaiting_user`；大量候选来自同一报告内的合并表、母公司表、审计附表或重复页，当前规则不能稳定选出唯一目标。
- 发现明确的报告期误判：000651 格力电器现金流量表被机器结果定位为 `2024-01-12`，而目标报告期为 `2024-12-31`。

### 结论与阻塞

- 本轮证明真实文件可取得、可检索并可复现，但不能证明 F004 的中文年报准确率；机器预标注不能替代 A/B 独立复核。
- 在修正候选去重、合并/母公司口径判定和报告期解析，并由两名独立复核者完成 30 个目标及冲突裁决前，F004 不得转为 `verified`。

## 2026-09-06：F004 真实样本规则修正回放

### 修正范围

- 严格区分完整日期和“2024 年 1—12 月”期间，避免把期间范围误解析为 `2024-01-12`。
- 对重复标题、审计报告提及、财务报表附注和“五年业绩摘要”增加确定性候选评分；只有唯一最高分的主表候选才能从多个候选中被定位，平分仍保留歧义。
- 保留全部原始候选和评分，不静默删除证据。

### 真实样本回放结果

- 对 10 份已取得报告执行完整 API 回放：上传、F003 解析、F004 识别均返回 201。
- 30/30 三表目标返回 `located`；30/30 的口径为 `consolidated`，报告期均为 `2024-12-31`，页级定位均被持久化。
- 修正后结果见 `data/real_reports/machine_preannotations_after_fix.json`。

### 结论与限制

- 本次修正消除了已发现的候选爆炸和 `2024-01-12` 报告期误判，具备进入人工复核的候选质量。
- 这仍是机器回放，不是独立黄金真值；尚未完成 Reviewer A/B 双盲复核、冲突裁决和准确率统计，因此 F004 仍不能转为 `verified`。

## 2026-09-06：F004 修正提交的独立 CI

- 远端提交：`11a1857b75eca78df5712858a3ebad0e3260d1ae`。
- GitHub Actions `CI`：`success`；PostgreSQL 17、全量迁移、Alembic 零漂移和完整检查通过。
- 证据：[CI run 34018998550](https://github.com/RXQ6/CiteFin/actions/runs/34018998550)。
- 该 CI 证明工程门禁通过，不替代真实中文年报的 Reviewer A/B 双盲复核、冲突裁决或 Goal Gate。

## 2026-09-06：F004 30 目标复核包

- 已制作 `docs/F004_REVIEW_PACKET.md`，明确 30 行目标队列、A/B 盲审字段、冲突裁决字段和交付标准。
- 复核包不包含机器预标注结论；当前没有新增人工标签或准确率统计。
- 下一步是由真实独立复核者填写 `data/real_reports/review_queue.csv`，不能由同一 Agent 生成 A/B 两套答案。

## 2026-09-06：F005 实验分支第一工作单元

### 实现范围

- 起点：先在隔离分支 `codex/f005-experimental` 完成第一工作单元，随后按主线 `provisional` 工程推进规则纳入当前分支。
- 新增 `FinancialFact` 模型、`20260906_0005` 迁移、确定性标签映射、Decimal 单位换算、幂等和冲突保留接口。
- 仅接受已有 F004 `located + consolidated` 结果；未知标签拒绝写入，冲突事实生成冲突组而不覆盖原始值。

### 验证结果

```text
targeted F005 tests: 12 passed
full pytest: 53 passed, coverage 90.66%
Ruff: passed; format: 40 files already formatted
mypy: Success, 21 source files
golden: 3/3 cases passed
alembic upgrade: base -> 20260904_0001 -> 20260904_0002 -> 20260906_0003 -> 20260906_0004 -> 20260906_0005
alembic check: No new upgrade operations detected
```

### 限制

- 当前主线只推进到本地 `candidate_complete`，不代表正式 `verified`；
- 测试使用合成输入，不代表真实中文年报字段标准化准确率；
- 不实现 F006 指标计算，也不把未经独立复核的真实年报作为黄金真值。

## 2026-09-06：主线 provisional 工程推进规则

- 功能目录新增透明 `provisional` 状态：它允许 F004→F005 工程推进，但不等同于 `verified`。
- F004 当前为 `provisional`，F005 已达到本地 `candidate_complete`；仅依据项目负责人批准的工程推进规则，不代表真实中文年报准确率已验证。
- `verified` 仍只能由 Goal Gate 写入；F006 及后续功能仍被 F005 正式验证门禁阻塞。
- 真实年报双人复核、裁决和准确率声明限制不变。

## 2026-09-06：F005 财务字段标准化

### 验证范围

- 核心报表标签映射到版本化标准概念，并保留原始标签和值、标准值、单位、币种、期间、合并口径和来源定位。
- 金额使用 Decimal 和显式单位换算；未知标签、非法值、非合并口径和缺失 F004 定位被拒绝。
- 相同身份和值的重复请求幂等；同一身份的不同值进入冲突组，原事实不被覆盖。
- F005 迁移可从空 SQLite 库升级到 head，且 Alembic 检查无新升级操作。

### 执行方式与结果

Windows 标准入口：

```powershell
.\scripts\dev.ps1 verify-feature -Feature F005
```

本次结果：

```text
full pytest: 53 passed, coverage 90.66%
Ruff: passed; format: 40 files already formatted
mypy: Success, 21 source files
golden: 3/3 cases passed
F005 targeted tests: 12 passed
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005
alembic check: No new upgrade operations detected
```

专项执行器为 `scripts/verify_f005.py`；测试输入为合成 F004 已定位事实，不包含未经独立复核的真实年报。

### 结论与限制

- F005 满足本地机器可执行验收，状态为 `candidate_complete`，并非 `verified`。
- `verified` 仍需独立 Goal Gate 写入；F004 的双人复核、裁决和真实准确率限制不变，F006 不启动。
- 不得据此声明真实中文年报字段标准化准确率。

## 2026-09-06：F004 独立复核交接包准备

### 执行方式与结果

```powershell
.\.venv\Scripts\python.exe scripts/prepare_f004_review.py
```

```text
manifest reports: 10 validated
review targets: 30 unique targets validated
PDF byte count, SHA-256 and page count: 10/10 matched
blank reviewer copies: reviewer_a.csv and reviewer_b.csv created
machine preannotation fields in copies: none
```

输出目录为 `artifacts/f004_review/`。该目录的 CSV 只包含目标身份字段，所有答案和证据字段为空。

### 结论与限制

- 复核材料已具备交付条件，但 A/B 人工标签、冲突裁决和一致率统计仍为空。
- 此工作单元不改变 F004 的 `provisional` 状态，不构成真实准确率证据，也不能由同一 Agent 代替 Reviewer A/B。

## 2026-09-07：F006 provisional 核心金融指标计算

### 验证范围

- 15 项核心指标使用 Decimal 确定性公式计算，并保存定义版本、计算器版本、输入事实 ID 和输入快照。
- 缺失输入、零分母和冲突事实返回结构化状态，不生成无穷值或猜测结果。
- 增加 `CalculatedMetric` 持久化模型、F006 SQLite 迁移和用户范围计算 API。
- 重复计算请求返回原结果；不同用户不能读取其他用户的运行。
- 仅使用现有合成黄金数据和契约事实；未将真实年报机器结果作为黄金真值。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F006
```

```text
Ruff: passed
format: 44 files already formatted
mypy: Success, 23 source files
golden: 3/3 cases passed
full pytest: 59 passed, coverage 91.40%
F006 targeted tests: 6 passed
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006
alembic check: No new upgrade operations detected
```

### 结论与限制

- F006 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- 15 项指标的工程计算和持久化契约已具备可复算证据；真实中文年报字段准确率仍未验证。
- F004 双人复核、F005/F006 正式 Goal Gate 和真实年报准确率声明限制保持不变。

## 2026-09-07：F007 provisional Evidence 数据模型

### 验证范围

- 增加 Claim 与 Evidence 持久化模型，支持来源页定位、FinancialFact、CalculatedMetric 和规则四类主证据。
- Claim 与 Evidence API 强制用户范围校验；Evidence 必须指向且只能指向一个主证据目标。
- 来源页定位必须存在于已解析的 `DocumentPage`；事实和指标必须属于同一分析运行。
- 证据支持 Claim 时更新支持状态，并写入不可变审计事件。
- F007 迁移可从空 SQLite 库升级到 head，且 Alembic 无漂移。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F007
```

```text
Ruff: passed
format: 47 files already formatted
mypy: Success, 25 source files
golden: 3/3 cases passed
full pytest: 61 passed, coverage 90.59%
F007 targeted tests: 2 passed
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007
alembic check: No new upgrade operations detected
```

### 结论与限制

- F007 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- 当前只提供证据实体和最小写入接口；报告生成、独立 Evaluator、Goal Gate 和真实年报证据覆盖率尚未完成。
- 真实年报双人复核和准确率声明限制保持不变。

## 2026-09-07：F008 LangGraph 运行状态

### 验证范围

- 增加 `FinanceAgentState` 类型化控制状态，仅保存运行标识、实体引用、节点、状态版本和时间边界，不复制 PDF 或报告正文。
- 增加版本化 `WorkflowNode` 枚举、数据质量/Goal Gate 路由函数和合法节点转移校验。
- `advance_state` 强制分析运行用户归属，持久化节点转移、状态更新、状态版本递增和 `AuditEvent`。
- 保留 provisional 工程边界：当前验证状态契约、确定性路由和审计边界，不宣称完整 LangGraph 执行器或真实年报准确率。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F008
```

```text
Ruff: passed
format: 50 files already formatted
mypy: Success, 26 source files
golden: 3/3 cases passed
full pytest: 87 passed, coverage 91.28%
F008 targeted tests: 26 passed
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007
alembic check: No new upgrade operations detected
```

### 结论与限制

- F008 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- F008 完成后按项目负责人指令暂停，不启动 F009 或其他后续功能。
- F004 双人复核、F005–F008 正式 Goal Gate 和真实年报准确率声明限制保持不变。

## 2026-09-07：F009 财务分析节点

### 验证范围

- 从已持久化的 15 项 `CalculatedMetric` 生成版本化计算 Claim；每条 Claim 保留 metric Evidence。
- 对缺失、冲突和零分母指标生成明确的 limitation Claim，不以零或无穷值替代。
- 使用带版本 `rule_id` 的确定性规则生成受控 inference Claim，并同时保存指标 Evidence 和规则 Evidence。
- API 强制用户范围和目标期间校验，结果按分析版本幂等重放；不生成交易指令，不允许无 Evidence 的数字结论。
- 保留 provisional 工程边界：未实现独立 Evaluator、风险实体、报告生成和真实年报准确率验证。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F009
```

```text
Ruff: passed
format: 54 files already formatted
mypy: Success, 28 source files
golden: 3/3 cases passed
full pytest: 93 passed, coverage 91.98%
F009 targeted tests: 6 passed
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007
alembic check: No new upgrade operations detected
```

### 结论与限制

- F009 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- F009 的数值来源是已有 `CalculatedMetric`，推断只由版本化规则生成；这证明工程链路可复算，不证明真实中文年报准确率。
- F004 双人复核、F005–F009 正式 Goal Gate 和真实年报准确率声明限制保持不变。

## 2026-09-07：F010 provisional 风险识别节点

### 验证范围

- 从同一分析运行、同一报告期的 15 项 `CalculatedMetric` 读取可用指标，使用版本化确定性规则生成风险发现。
- 每个风险发现保存严重程度、类别、限制、置信度、规则代码和 Claim 引用；高严重度发现同时关联至少一个 `FinancialFact` 和一个规则或指标 Evidence。
- 缺失、冲突或零分母指标生成 `data_quality` 限制，置信度为 0，并停止对应风险规则判断；缺少高风险事实引用时严重程度降级。
- API 强制用户范围与报告期校验，结果按运行和报告期幂等重放；输出不包含收益保证或无条件买卖建议。
- 新增 `RiskFinding` 模型、F010 SQLite 迁移、风险 API、专项验证器和迁移契约测试。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F010
```

```text
Ruff: passed
format: 58 files already formatted
mypy: Success, 30 source files
golden: 3/3 cases passed
full pytest: 98 passed, coverage 92.27%
F010 targeted tests: 5 passed, 1 warning
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008
alembic check: No new upgrade operations detected
```

### 结论与限制

- F010 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- 当前规则只证明确定性工程链路、证据挂接、数据不足降级和幂等 API；不证明真实中文年报风险识别准确率。
- F004 双人复核、F005–F010 正式 Goal Gate 和真实年报准确率声明限制保持不变；不启动 F011。

## 2026-09-07：F011 provisional 报告生成

### 验证范围

- 从已持久化的 `FinancialFact`、`CalculatedMetric`、`Claim`、`Evidence` 和 `RiskFinding` 只读组装 `financial-report-v1` 版本化报告。
- 报告分区呈现事实、计算、推断、风险、限制和 Evidence 映射；重大 Claim 必须有可定位证据，缺失或不支持的重大 Claim 阻止候选报告生成。
- 报告保存 `candidate` 状态、版本、Claim 引用和生成器版本；重复请求返回同一报告，不修改事实或指标。
- API 强制用户范围和报告期校验；不生成交易指令、收益保证或无条件买卖建议。
- 新增 `Report` 模型、F011 SQLite 迁移、报告 API、专项验证器和迁移契约测试。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F011
```

```text
Ruff: passed
format: 62 files already formatted
mypy: Success, 32 source files
golden: 3/3 cases passed
full pytest: 102 passed, coverage 92.16%
F011 targeted tests: 4 passed, 1 warning
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008 -> 0009
alembic check: No new upgrade operations detected
```

### 结论与限制

- F011 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- 当前只证明合成/契约输入下的报告 Schema、证据引用和只读组装链路；不证明真实中文年报报告质量或准确率。
- F004 双人复核、F005–F011 正式 Goal Gate 和真实年报准确率声明限制保持不变；不启动 F012。

## 2026-09-07：F012 provisional 独立 Evaluator

### 验证范围

- 从已持久化的事实、指标、Claim、Evidence、RiskFinding、Report 和 AuditEvent 只读评测候选报告，不调用报告生成器或业务工具。
- 检查报告 Schema、Claim/Evidence 覆盖与引用完整性、指标计算谱系、风险追溯、禁止投资措辞和报告审计事件。
- 保存 `Evaluation` 的版本、状态、逐项检查、阻断原因、输入实体 ID/数量、报告内容哈希、最小修复节点和修复指令；重复评测返回同一结果，不修改报告或运行的 `verified` 状态。
- 新增 `Evaluation` 模型、F012 SQLite 迁移、用户隔离评测 API、专项验证器和迁移契约测试。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F012
```

```text
Ruff: passed
format: 66 files already formatted
mypy: Success, 34 source files
golden: 3/3 cases passed
full pytest: 106 passed, coverage 91.10%
F012 targeted tests: 4 passed, 1 warning
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008 -> 0009 -> 0010
alembic check: No new upgrade operations detected
```

### 结论与限制

- F012 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- 当前只证明合成/契约输入下的独立评测结果、失败修复路由和可审计快照；不证明真实中文年报报告质量或准确率。
- F004 双人复核、F005–F012 正式 Goal Gate 和真实年报准确率声明限制保持不变；不启动 F013。

## 2026-09-07：F013 provisional Goal Gate

### 验证范围

- 新增唯一 Goal Gate 服务和 `GoalGateDecision` 持久化实体，要求当前候选报告存在独立 Evaluation 且所有必需检查通过后才允许写入 `verified`。
- 验证通过、评测失败修订、缺少评测阻断、幂等重放、用户隔离和普通工作流迁移禁止伪造 `verified`。
- 通过时冻结报告并完成运行；失败时保留候选报告，写入最小修复节点、阻断原因、修复指令、证据引用和 `goal_gate_decision` 审计事件。
- 新增 F013 SQLite 迁移、Goal Gate API、专项验证器、迁移契约测试和工作流边界测试。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F013
```

```text
Ruff: passed
format: 69 files already formatted
mypy: Success, 36 source files
golden: 3/3 cases passed
full pytest: 110 passed, coverage 91.21%
F013 targeted tests: 6 passed, 1 warning
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008 -> 0009 -> 0010 -> 0011
alembic check: No new upgrade operations detected
```

### 结论与限制

- F013 达到 provisional 工程 `candidate_complete`，不等于真实生产 Goal Gate 或正式 `verified`。
- 当前只证明合成/契约 Evaluation 下的终止状态边界、失败路由、审计和幂等行为；不证明真实中文年报准确率。
- F004 双人复核、F005–F013 正式 Goal Gate 外部证据和真实年报准确率声明限制保持不变；不启动 F014。

## 2026-09-07：F014 provisional Checkpoint 恢复

### 验证范围

- 将初始运行快照统一为可验证的 `FinanceAgentState`，并保存版本化 `thread_id`、工作流节点、状态版本和来源哈希引用。
- 验证 Checkpoint 保存的工作流版本、来源归属/哈希、状态版本递增、同版本冲突和跨用户隔离。
- 验证恢复时的状态契约、工作流版本、节点、线程和来源哈希校验；恢复会更新运行控制状态并写入一次 `checkpoint_restored` 审计事件。
- 验证重复保存和重复恢复只返回原结果，不重复创建 Checkpoint 或恢复审计副作用。
- 新增 F014 Checkpoint 服务、API、专项验证器和集成测试；不新增迁移，因为既有 `workflow_checkpoints` 表已满足持久化契约。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F014
```

```text
Ruff: passed
format: 72 files already formatted
mypy: Success, 38 source files
golden: 3/3 cases passed
full pytest: 115 passed, coverage 90.70%
F014 targeted tests: 5 passed, 1 warning
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008 -> 0009 -> 0010 -> 0011
alembic check: No new upgrade operations detected
```

### 结论与限制

- F014 达到 provisional 工程 `candidate_complete`，不等于完整 LangGraph 生产执行器或正式 `verified`。
- 当前只证明合成/契约状态下的版本化恢复、来源完整性和幂等副作用边界；不证明黄金流程恢复成功率或真实中文年报准确率。
- F004 双人复核、F005–F014 正式 Goal Gate 外部证据和真实年报准确率声明限制保持不变；不启动 F015。

## 2026-09-07：F015 provisional 运行进度接口

### 验证范围

- 查询用户拥有的 `AnalysisRun` 状态、当前节点、工作流版本、生命周期时间、任务摘要和最近结构化错误。
- 验证其他用户不能读取运行状态或生命周期事件，错误响应不泄露内部错误正文、提示词或密钥字段。
- 通过 `event_id + created_at` 的稳定顺序提供有限 SSE 生命周期事件快照，支持 `Last-Event-ID` 或 `after` 游标重连。
- 事件 payload 仅输出白名单元数据；原始 `AuditEvent.payload` 不直接暴露。
- 新增 F015 进度服务、API、专项验证器和集成测试；不新增迁移，因为事件查询复用既有 `AuditEvent`。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F015
```

```text
Ruff: passed
format: 75 files already formatted
mypy: Success, 40 source files
golden: 3/3 cases passed
full pytest: 119 passed, coverage 90.96%
F015 targeted tests: 4 passed, 1 warning
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008 -> 0009 -> 0010 -> 0011
alembic check: No new upgrade operations detected
```

### 结论与限制

- F015 达到 provisional 工程 `candidate_complete`，不等于生产级实时事件总线、长连接推送或正式 `verified`。
- 当前只证明合成/契约运行下的用户隔离、状态摘要、事件排序、游标重连和 payload 脱敏；不证明生产认证和多实例部署行为。
- F004 双人复核、F005–F015 正式 Goal Gate 外部证据和真实年报准确率声明限制保持不变；不启动 F016。

## 2026-09-07：F016 provisional 最小前端

### 验证范围

- FastAPI 根路径提供最小 UI，页面包含用户标识、公司名称、证券代码、报告期、分析关注点和 PDF 上传控件。
- 页面调用已有 `POST /api/v1/analysis-runs` 和 `POST /api/v1/analysis-runs/{run_id}/documents`，错误只显示可操作的稳定错误信息。
- 页面通过已有进度接口和有限 SSE 事件快照显示服务端状态，并以事件游标重连；没有本地生成的运行状态。
- 页面提供键盘焦点样式和响应式布局；新增前端契约测试、F016 验证器和开发脚本入口；不新增数据库迁移。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F016
node --check src/citefin/static/assets/app.js
```

```text
Ruff: passed
format: 76 files already formatted
mypy: Success, 42 source files
golden: 3/3 cases passed
full pytest: 121 passed, 1 warning, coverage 90.98%
F016 frontend contract tests: 2 passed (included in full pytest)
F016 verification script: passed
JavaScript syntax check: passed
```

首次执行 F016 门禁曾因 `src/citefin/main.py` 未经过 Ruff 格式化而停止；运行项目格式化入口后重新执行，以上结果为最终成功结果。

### 结论与限制

- F016 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- 当前只证明静态 UI、既有上传/进度 HTTP 契约、事件游标消费、键盘焦点和响应式资源的工程行为；不证明生产级认证、长连接事件推送、完整工作流执行、真实年报准确率或端到端完成率。
- F004 双人复核、F005–F016 正式 Goal Gate 外部证据和真实年报准确率声明限制保持不变；F017 证据查看界面和 F018 端到端验收尚未启动。

## 2026-09-07：F017 provisional 证据查看界面

### 验证范围

- 验证用户范围 evidence-view API 能将报告 Claim、Evidence、Fact/Metric 来源链解析为文件、页码、locator 和最多 500 字符的页文本片段。
- 验证点击结论时前端使用受保护 PDF 内容接口读取不可变对象，并以浏览器 blob `#page=N` 定位来源页；用户标识不写入 URL。
- 验证其他用户无法读取证据视图或 PDF，读取对象前校验 SHA-256 内容地址。
- 验证缺失 Evidence、规则型 Evidence、未解析页、来源缺失和越界页返回明确状态与原因。
- F017 不新增迁移；全量测试包含既有迁移契约检查。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F017
uv run pytest tests/integration/test_evidence_viewer_api.py tests/integration/test_frontend.py --no-cov
node --check src/citefin/static/assets/app.js
```

```text
Ruff: passed
format: 79 files already formatted
mypy: Success, 44 source files
golden: 3/3 cases passed
full pytest: 124 passed, 1 warning, coverage 90.89%
F017 targeted tests: 5 passed, 1 warning
F017 verification script: passed
JavaScript syntax check: passed
```

首次定向测试的 5 个断言全部通过，但因只运行局部测试导致项目全局覆盖率为 46.90%，命令被 90% 门槛拒绝；改用 `--no-cov` 复跑定向集，并由完整门禁验证全量覆盖率。首次完整门禁另发现 metric 来源引用列表缺少显式可空 locator 类型注解；修正后以上最终门禁通过。

### 结论与限制

- F017 达到 provisional 工程 `candidate_complete`，不等于正式 `verified`。
- 当前只证明合成/契约数据下的只读证据投影、片段边界、页级跳转、对象完整性和用户隔离；不证明真实中文年报证据覆盖率、页码准确率或人工复核结果。
- F004 双人复核及 F005–F017 正式 Goal Gate 外部证据仍待完成；F018 只允许执行可复现的合成黄金流程验收，不得冒充真实生产验收。

## 2026-09-07：F018 端到端验收

### 验证范围

- 使用 G001 的 23 项合成事实和 15 项预期指标，通过公开 HTTP API 串联运行创建、三页 PDF 上传、解析、三表识别、事实标准化、指标、财务分析、风险、报告、证据查看、Evaluator 与 Goal Gate。
- 验证运行创建、上传、解析、三表识别、事实、指标、分析、风险、报告、评测和 Gate 的重放不产生重复业务实体；Checkpoint 保存与恢复各只产生一个副作用事件。
- 逐条统计合成报告的重大 Claim，要求每条至少有一个状态为 `available` 的来源页；读取受保护 PDF 并与上传字节完全一致。
- 另建缺少 Evidence 的重大 Claim，验证独立评测失败后 Gate 返回 `revision_required`，进度无 `completed_at` 且报告保持 `candidate`。
- F018 未新增迁移；同时补齐 F005 公开标准化接口与 F006 指标引擎之间的规范概念映射。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 verify-feature -Feature F018
```

```text
Ruff: passed
format: 80 files already formatted
mypy: Success, 44 source files
golden: 3/3 cases passed
full pytest: 134 passed, 1 warning, coverage 90.91%
F018 targeted success/failure flows: 2 passed, 1 warning
F018 verification script: passed
```

开发期间的首轮定向运行先因未指定项目内 `UV_CACHE_DIR` 和 pytest 临时目录而遇到工作区外写权限错误；改用项目脚本同等环境后继续。随后验收依次发现 F005 缺少指标所需标签映射、`流动负债合计` 与 `负债合计` 正则重叠、Decimal 黄金值精度口径和评测检查字段名断言问题；逐项修正后，以上完整门禁为最终结果。

### 结论与限制

- F018 达到 provisional 工程 `candidate_complete`；产品清单 F001–F018 已无 `not_started` 功能，但 F004 及 F005–F018 的正式外部验证状态没有被改写。
- G001 合成流程中的重大 Claim 页级证据覆盖率为 100%；该分母只包含本次合成报告的重大 Claim，不是生产指标，也不代表真实中文年报证据覆盖率或准确率。
- 事实由测试以 `manual` 方式经公开 API 提交，未验证自动表格抽取、真实用户认证、多实例部署、真实年报人工真值或 Reviewer A/B；正式 `verified` 仍需独立证据与 Goal Gate。

## 2026-09-08：完整工作台只读聚合 API

### 验证范围

- 用户只能列出自己的分析运行，并按最近更新时间获得稳定排序。
- 工作台投影从持久化实体读取来源、三表、事实、指标、Claim、风险、报告、Evaluator、Goal Gate 和 Checkpoint 摘要。
- 空运行返回真实空集合；其他用户读取同一运行返回 404。
- 响应不暴露 `storage_uri`、完整 `state_data` 或原始审计 payload。

### 执行方式与结果

```powershell
uv run pytest tests/integration/test_workbench_api.py --no-cov
.\scripts\dev.ps1 check
```

```text
targeted workbench tests: 2 passed, 1 warning
Ruff: passed; format: 83 files
mypy: Success, 46 source files
golden: 3/3 cases passed
full pytest: 136 passed, 1 warning
coverage: 91.40% (required 90%)
```

### 结论与限制

- 只读工作台投影通过完整质量门禁且未新增迁移。
- 该接口只呈现真实持久化状态，不执行或模拟完整工作流；前端分阶段操作和最终交互验证仍在进行中。
- 验证使用合成/契约数据，不证明真实中文年报准确率、生产认证或正式 Goal Gate。

## 2026-09-08：完整财报研究工作台

### 验证范围

- 工作台可按本地用户标识列出和恢复已有运行，并显示真实进度、任务、脱敏错误和有限 SSE 事件。
- 页面接入上传、解析、三表识别、F005 人工事实确认、15 项指标、财务分析、风险、候选报告、Evaluator、Goal Gate 和 Checkpoint 恢复接口。
- 指标显示状态、版本和输入快照；风险显示严重度、置信度与限制；报告区分事实、计算、推断、风险和限制。
- 证据浏览器继续通过受保护 PDF 内容接口和 blob `#page=N` 跳转，不在 URL 中写入用户标识。
- 服务端文本使用 DOM `textContent` 渲染，前端源码不使用 `innerHTML`；页面保留键盘焦点、跳转链接、响应式布局和减少动画偏好。

### 执行方式与结果

```powershell
node --check src/citefin/static/assets/app.js
uv run pytest tests/integration/test_frontend.py --no-cov
uv run python scripts/verify_f016.py
uv run python scripts/verify_f017.py
.\scripts\dev.ps1 check
Invoke-WebRequest http://127.0.0.1:8000/
```

```text
JavaScript syntax: passed
frontend contract tests: 3 passed, 1 warning
F016 verifier: passed
F017 verifier: passed
Ruff: passed; format: 83 files
mypy: Success, 46 source files
golden: 3/3 cases passed
full pytest: 137 passed, 1 warning
coverage: 91.40% (required 90%)
local root route: HTTP 200, text/html
```

### 结论与限制

- 完整工作台能从真实持久化实体恢复视图，并调用既有后端能力；没有模拟数据或浏览器生成的完成状态。
- 当前没有完整自动工作流执行器和自动表格字段抽取，用户必须按阶段操作并人工确认 F005 事实；这在界面中明确披露。
- 本次验证是静态契约、本地 HTTP 和合成/契约后端验证，不是生产浏览器矩阵、生产认证、真实年报准确率或正式外部 Goal Gate。

## 2026-09-08：完整工作台最终交付门禁

### 执行方式

```powershell
.\scripts\dev.ps1 verify-feature -Feature F016
.\scripts\dev.ps1 verify-feature -Feature F017
.\scripts\dev.ps1 verify-feature -Feature F018
node --check src/citefin/static/assets/app.js
python -m alembic upgrade head
python -m alembic check
```

### 结果

```text
F016: full check passed; F016 verifier passed
F017: full check passed; F017 verifier passed
F018: full check passed; synthetic success/failure flows 2 passed; F018 verifier passed
each full check: 137 pytest passed, 1 warning, coverage 91.40%
Ruff: passed; format: 83 files
mypy: Success, 46 source files
golden: 3/3 cases passed
JavaScript syntax: passed
alembic upgrade: base -> 0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 -> 0008 -> 0009 -> 0010 -> 0011
alembic check: No new upgrade operations detected
```

### 结论与限制

- 完整工作台及其读取 API 通过现有 F016–F018 工程门禁，迁移从空 SQLite 库升级成功且 ORM 无漂移。
- 唯一警告仍是 Starlette TestClient 使用 AnyIO 已弃用别名，不影响断言与覆盖率门禁。
- F018 结果来自可复现合成流程；未执行真实交易，未生成无证据投资建议，也不构成真实年报准确率、生产浏览器矩阵或正式外部 Goal Gate 证据。

## 2026-09-08：GitHub 双语项目状态页

### 验证范围

- 中文与英文状态页均引用 `FEATURES.json` 和 `docs/VALIDATION.md` 作为详细事实来源。
- 两个页面互相链接，README 同时提供中英文入口。
- 状态数字与 `FEATURES.json` 一致：3 个 `verified`、1 个 `provisional`、14 个 `candidate_complete`。
- 文档明确披露合成验证边界、待完成的生产化工作和禁止真实交易/无证据投资建议的约束。

### 执行方式

```powershell
git diff --check
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 test
```

```text
setup: 73 packages checked
pytest: 137 passed, 1 warning
coverage: 91.40% (required 90%)
git diff --check: passed
```

### 结论与限制

- 双语页面是当前项目状态的 GitHub 展示摘要，不替代 `FEATURES.json` 中的正式状态或专项验证证据。
- 本次只增加和链接文档，不改变 F001–F018 状态，也不构成真实年报准确率或生产验收证据。

## 2026-09-08：GitHub 三语言详细 README

### 验证范围

- `README.md`、`README.zh-CN.md`、`README.ja.md` 分别提供英文、简体中文和日文项目说明。
- 三个页面顶部均提供 EN、ZH、JA 语言徽章，并链接到仓库内对应文件。
- 三版均说明产品定位、证据链、工作台、分析工作流、15 项指标、F001–F018 状态、架构、安装、API、验证、安全限制和下一阶段。
- 逐份检查 `FEATURES.json`、`docs/VALIDATION.md` 和三语言 README 等关键本地链接，所有目标均存在。
- 功能状态保持为 3 个 `verified`、1 个 `provisional`、14 个 `candidate_complete`，没有伪造正式完成状态。

### 执行方式与结果

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 test
git diff --check
```

```text
setup: 73 packages checked
pytest: 137 passed, 1 warning
coverage: 91.40% (required 90%)
local Markdown links: all checked targets exist
git diff --check: passed
```

### 结论与限制

- 三语言 README 通过链接与完整回归检查，可作为 GitHub 首页及语言切换页面。
- README 中的通过数和覆盖率来自本次项目测试；F018 仍只证明合成流程，不证明真实年报准确率或生产验收。
