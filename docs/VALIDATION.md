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
