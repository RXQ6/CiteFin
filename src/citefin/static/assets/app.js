const API_BASE = "/api/v1";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {
  userId: null,
  runId: null,
  runs: [],
  workspace: null,
  progress: null,
  events: [],
  lastEventId: null,
  refreshTimer: null,
  pdfObjectUrl: null,
  pendingCheckpoint: null,
};

const statusLabels = {
  created: "已创建",
  validating: "校验中",
  running: "运行中",
  candidate_complete: "候选完成",
  evaluating: "评测中",
  verified: "已验证",
  awaiting_user: "等待确认",
  revision_required: "需要修订",
  blocked: "已阻断",
  failed: "失败",
  ready: "就绪",
  in_progress: "进行中",
  not_started: "未开始",
  passed: "通过",
};
const statusTone = (value) => {
  if (["verified", "passed", "calculated", "located", "supported", "success"].includes(value)) return "good";
  if (["failed", "blocked", "critical", "high", "error"].includes(value)) return "bad";
  if (["revision_required", "awaiting_user", "medium", "conflict", "missing_input", "zero_denominator"].includes(value)) return "warn";
  return "neutral";
};
const metricLabels = {
  revenue_growth: "营业收入增长率", net_profit_growth: "净利润增长率", gross_margin: "毛利率",
  net_margin: "净利率", roa: "总资产收益率", roe: "净资产收益率", debt_to_assets: "资产负债率",
  current_ratio: "流动比率", quick_ratio: "速动比率", interest_coverage: "利息保障倍数",
  cash_to_short_term_debt: "现金短债比", operating_cash_flow_to_net_profit: "经营现金流 / 净利润",
  free_cash_flow: "自由现金流", receivables_growth: "应收账款增长率", inventory_growth: "存货增长率",
};
const statementLabels = { balance_sheet: "合并资产负债表", income_statement: "合并利润表", cashflow_statement: "合并现金流量表" };
const claimTypeLabels = { fact: "事实", calculation: "计算", inference: "推断", limitation: "限制" };
const errorLabels = {
  analysis_run_not_found: "找不到该分析运行", run_not_found: "找不到该分析运行",
  database_not_configured: "服务端尚未配置数据库", file_too_large: "文件超过大小限制",
  invalid_pdf: "文件不是有效 PDF", pdf_encrypted: "PDF 已加密", pdf_not_searchable: "PDF 不可检索",
  report_not_found: "尚未生成报告", source_document_not_found: "找不到源文件",
  storage_integrity_error: "源 PDF 完整性校验失败", no_supported_claims: "尚无可进入报告的受支持结论",
  missing_input: "计算所需事实不完整", statement_not_identified: "三张表尚未完成定位",
};
const locatorReasons = {
  claim_evidence_missing: "报告引用的 Evidence 不可用。", claim_has_no_evidence: "这条结论没有关联 Evidence。",
  claim_has_no_page_evidence: "这条结论没有可定位的 PDF 页级证据。", evidence_target_unresolved: "Evidence 目标无法解析。",
  page_not_parsed: "来源页尚未成功解析。", page_out_of_range: "证据页码超出源文件范围。",
  rule_has_no_source_page: "规则 Evidence 不对应 PDF 页面。", source_document_not_found: "来源文件不存在。",
  source_page_unavailable: "来源页当前不可用。",
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function clearAndEmpty(target, message) {
  target.replaceChildren(node("p", "empty-copy", message));
}
function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN");
}
function compactId(value) {
  if (!value) return "—";
  return value.length > 22 ? `${value.slice(0, 12)}…${value.slice(-6)}` : value;
}
function explainApiError(body, fallback) {
  const detail = body?.detail;
  if (detail && typeof detail === "object") {
    const code = typeof detail.code === "string" ? detail.code : "request_failed";
    const label = errorLabels[code] ?? "请求未完成";
    const message = typeof detail.message === "string" ? detail.message : "请检查前置条件后重试。";
    return `${label}（${code}）：${message}`;
  }
  if (typeof detail === "string") return detail;
  return fallback;
}
async function requestJson(url, options = {}, fallback = "请求未完成。") {
  let response;
  try { response = await fetch(url, options); } catch { throw new Error("无法连接服务端，请确认 API 正在运行。"); }
  let body = null;
  try { body = await response.json(); } catch { /* stable fallback */ }
  if (!response.ok) throw new Error(explainApiError(body, fallback));
  return body;
}
function headers(extra = {}) { return { "X-User-ID": state.userId, ...extra }; }
function makeIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return `workbench-${crypto.randomUUID()}`;
  return `workbench-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
function showToast(message, tone = "good") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.hidden = true; }, 4200);
}
function setWorkspaceMessage(message, kind = "info") {
  const target = $("#workspace-message");
  target.textContent = message;
  target.className = `notice notice-${kind}`;
  target.hidden = !message;
}
function chip(value) {
  const element = node("span", "state-chip", statusLabels[value] ?? value ?? "—");
  element.dataset.tone = statusTone(value);
  return element;
}

async function loadRuns(selectFirst = false) {
  if (!state.userId) return;
  state.runs = await requestJson(`${API_BASE}/analysis-runs`, { headers: headers() }, "无法载入分析任务。");
  renderRuns();
  if (selectFirst && state.runs.length) await selectRun(state.runs[0].run_id);
}
function renderRuns() {
  const list = $("#run-list");
  list.replaceChildren();
  if (!state.runs.length) return clearAndEmpty(list, "该用户还没有分析任务。");
  state.runs.forEach((run) => {
    const button = node("button", `run-item${run.run_id === state.runId ? " is-active" : ""}`);
    button.type = "button";
    const title = node("strong", "", run.company_name);
    const meta = node("span", "run-item-meta");
    meta.append(node("span", "", `${run.security_code} · ${run.report_period_end}`), node("span", "", statusLabels[run.status] ?? run.status));
    button.append(title, meta);
    button.addEventListener("click", () => selectRun(run.run_id));
    list.append(button);
  });
}
async function selectRun(runId) {
  state.runId = runId;
  state.lastEventId = null;
  state.events = [];
  clearPdf();
  renderRuns();
  $("#welcome-view").hidden = true;
  $("#workspace-view").hidden = false;
  setWorkspaceMessage("正在读取持久化工作区…", "info");
  try {
    await Promise.all([refreshWorkspace(), refreshProgress(), refreshEvents()]);
    setWorkspaceMessage("");
    startRefreshLoop();
  } catch (error) {
    setWorkspaceMessage(error instanceof Error ? error.message : "工作区读取失败。", "error");
  }
}
async function refreshWorkspace() {
  if (!state.runId) return;
  state.workspace = await requestJson(`${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/workspace`, { headers: headers() }, "无法读取工作台数据。");
  renderWorkspace();
}
async function refreshProgress() {
  if (!state.runId) return;
  state.progress = await requestJson(`${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/progress`, { headers: headers() }, "无法读取运行进度。");
  renderProgress();
}
function parseEventStream(body) {
  return body.split("\n\n").map((frame) => frame.trim()).filter(Boolean).map((frame) => {
    const lines = frame.split("\n");
    const idLine = lines.find((line) => line.startsWith("id: "));
    const dataLine = lines.find((line) => line.startsWith("data: "));
    if (!idLine || !dataLine) return null;
    try { return { id: idLine.slice(4), data: JSON.parse(dataLine.slice(6)) }; } catch { return null; }
  }).filter(Boolean);
}
async function refreshEvents() {
  if (!state.runId) return;
  const query = new URLSearchParams({ limit: "100" });
  if (state.lastEventId) query.set("after", state.lastEventId);
  const response = await fetch(`${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/events?${query}`, { headers: headers() });
  if (!response.ok) return;
  parseEventStream(await response.text()).forEach((event) => {
    if (!state.events.some((known) => known.id === event.id)) state.events.push(event);
    state.lastEventId = event.id;
  });
  renderEvents();
}
function startRefreshLoop() {
  if (state.refreshTimer) window.clearInterval(state.refreshTimer);
  state.refreshTimer = window.setInterval(async () => {
    try { await Promise.all([refreshProgress(), refreshEvents()]); } catch { /* visible state remains last confirmed */ }
  }, 5000);
}

function renderWorkspace() {
  const { run } = state.workspace;
  $("#run-code").textContent = `${run.security_code} · ${run.analysis_focus.join(" / ")}`;
  $("#run-company").textContent = run.company_name;
  $("#run-period").textContent = `报告期 ${run.report_period_end}`;
  $("#run-as-of").textContent = `截至 ${formatDateTime(run.as_of)}`;
  $("#run-id").textContent = compactId(run.run_id);
  $("#run-id").title = run.run_id;
  $("#run-status").textContent = statusLabels[run.status] ?? run.status;
  $("#run-status").dataset.tone = statusTone(run.status);
  $("#current-node").textContent = run.current_node ?? "—";
  renderSummary();
  renderPipeline();
  renderSourcesAndStatements();
  renderFacts();
  renderMetrics();
  renderRisks();
  renderReport();
  renderEvaluation();
  renderGate();
  renderCheckpoints();
}
function renderSummary() {
  const w = state.workspace;
  const highRisks = w.risks.filter((risk) => ["critical", "high"].includes(risk.severity)).length;
  const supportedMajor = w.claims.filter((claim) => claim.materiality === "major" && claim.status === "supported").length;
  const items = [
    ["来源文件", String(w.sources.length)], ["已存事实", String(w.facts.length)], ["已计算指标", `${w.metrics.filter((m) => m.status === "calculated").length} / ${w.metrics.length || 15}`],
    ["高等级风险", String(highRisks)], ["受支持重大结论", String(supportedMajor)],
  ];
  const target = $("#summary-strip"); target.replaceChildren();
  items.forEach(([label, value]) => { const cell = node("div", "summary-cell"); cell.append(node("span", "", label), node("strong", "", value)); target.append(cell); });
}
function renderPipeline() {
  const w = state.workspace;
  const located = w.statements.filter((item) => item.status === "located").length;
  const latestEval = w.evaluations[0];
  const latestGate = w.gate_decisions[0];
  const stages = [
    { title: "上传年度报告", detail: w.sources.length ? `${w.sources[0].file_name} · ${w.sources[0].page_count} 页` : "尚无来源文件", complete: w.sources.length > 0, action: "attach", label: "上传" },
    { title: "解析 PDF 页面", detail: "提取页级文本、哈希与坐标索引", complete: state.events.some((e) => e.data.event_type === "document_parsed"), action: "parse", label: "解析 / 重放" },
    { title: "定位三张合并报表", detail: `${located} / 3 已定位`, complete: located === 3, action: "statements", label: "识别 / 重放" },
    { title: "确认标准化事实", detail: `${w.facts.length} 条持久化事实`, complete: w.facts.length > 0, action: "facts", label: "打开录入" },
    { title: "计算 15 项指标", detail: `${w.metrics.length} 项结果`, complete: w.metrics.length === 15, action: "metrics", label: "计算 / 重放" },
    { title: "形成财务结论", detail: `${w.claims.length} 条原子 Claim`, complete: w.claims.length > 0, action: "analysis", label: "分析 / 重放" },
    { title: "识别风险", detail: `${w.risks.length} 项风险或限制`, complete: w.risks.length > 0, action: "risks", label: "识别 / 重放" },
    { title: "生成候选报告", detail: w.reports.length ? `报告 v${w.reports[0].version}` : "尚无报告", complete: w.reports.length > 0, action: "report", label: "生成 / 重放" },
    { title: "独立 Evaluator", detail: latestEval ? `结果：${statusLabels[latestEval.status] ?? latestEval.status}` : "尚未评测", complete: latestEval?.status === "passed", action: "evaluate", label: "运行评测" },
    { title: "Goal Gate", detail: latestGate ? `判定：${statusLabels[latestGate.decision] ?? latestGate.decision}` : "尚未判定", complete: latestGate?.decision === "verified", action: "gate", label: "提交判定" },
  ];
  const list = $("#pipeline-list"); list.replaceChildren();
  stages.forEach((stage, index) => {
    const row = node("div", `pipeline-row${stage.complete ? " is-complete" : ""}`);
    row.append(node("span", "pipeline-index", stage.complete ? "✓" : String(index + 1).padStart(2, "0")));
    const copy = node("div", "pipeline-copy"); copy.append(node("strong", "", stage.title), node("small", "", stage.detail)); row.append(copy);
    const button = node("button", "button button-secondary", stage.label); button.type = "button"; button.dataset.action = stage.action;
    button.disabled = !isActionReady(stage.action); row.append(button); list.append(row);
  });
}
function isActionReady(action) {
  const w = state.workspace;
  if (action === "attach") return !w.sources.length;
  if (["parse", "statements"].includes(action)) return w.sources.length > 0;
  if (action === "facts") return w.statements.some((item) => item.status === "located");
  if (action === "metrics") return w.facts.length > 0;
  if (["analysis", "risks"].includes(action)) return w.metrics.length > 0;
  if (action === "report") return w.claims.length > 0;
  if (action === "evaluate") return w.reports.length > 0;
  if (action === "gate") return w.reports.length > 0 && w.evaluations.length > 0;
  return true;
}

function renderProgress() {
  const p = state.progress; if (!p) return;
  $("#task-count").textContent = String(p.tasks.length);
  const tasks = $("#task-list"); tasks.replaceChildren();
  if (!p.tasks.length) clearAndEmpty(tasks, "服务端未返回运行任务。");
  p.tasks.forEach((task) => { const card = node("div", "task-card"); const copy = node("div"); copy.append(node("strong", "", task.title), node("small", "", `${task.feature_id} · 尝试 ${task.attempt_count}`)); card.append(copy, chip(task.status)); tasks.append(card); });
  const errors = $("#error-list"); errors.replaceChildren();
  if (!p.recent_errors.length) clearAndEmpty(errors, "暂无服务端错误。");
  p.recent_errors.forEach((error) => { const row = node("div", "compact-row"); const copy = node("div"); copy.append(node("strong", "", error.code), node("small", "", `${error.node} · ${formatDateTime(error.created_at)}`)); row.append(copy, chip(error.status)); errors.append(row); });
}
function renderEvents() {
  $("#event-count").textContent = String(state.events.length);
  const list = $("#event-list"); list.replaceChildren();
  if (!state.events.length) return clearAndEmpty(list, "尚未收到生命周期事件。");
  [...state.events].reverse().forEach((event) => { const item = node("li"); item.append(node("strong", "", `${event.data.event_type} · ${event.data.status}`), node("time", "", formatDateTime(event.data.created_at)), node("code", "", compactId(event.id))); list.append(item); });
}

function renderSourcesAndStatements() {
  const w = state.workspace; const sources = $("#source-list"); sources.replaceChildren();
  const select = $("#fact-source"); select.replaceChildren();
  if (!w.sources.length) {
    clearAndEmpty(sources, "尚未上传来源文件。");
    const picker = node("input"); picker.type = "file"; picker.accept = "application/pdf,.pdf"; picker.id = "attach-file";
    const button = node("button", "button button-primary", "上传 PDF"); button.type = "button"; button.dataset.action = "attach";
    sources.append(picker, button);
  } else w.sources.forEach((source) => {
    const card = node("div", "source-card"); card.append(node("strong", "", source.file_name), node("code", "", `${source.page_count} 页 · SHA-256 ${compactId(source.sha256)} · ${source.parser_version}`)); sources.append(card);
    const option = node("option", "", source.file_name); option.value = source.source_id; select.append(option);
  });
  const statements = $("#statement-list"); statements.replaceChildren();
  $("#statement-count").textContent = `${w.statements.filter((item) => item.status === "located").length} / 3`;
  const byType = new Map(w.statements.map((item) => [item.statement_type, item]));
  Object.entries(statementLabels).forEach(([type, label]) => {
    const item = byType.get(type); const card = node("div", "statement-card"); card.append(node("strong", "", label));
    if (item) card.append(chip(item.status), node("small", "", item.page_number ? `第 ${item.page_number} 页 · ${item.algorithm_version}` : `候选 ${item.candidate_count} · ${item.algorithm_version}`));
    else card.append(chip("not_started"), node("small", "", "尚无持久化识别结果"));
    statements.append(card);
  });
  $("#fact-period-end").value = w.run.report_period_end;
}
function renderFacts() {
  const facts = state.workspace.facts; $("#fact-count").textContent = String(facts.length);
  const body = $("#fact-table"); body.replaceChildren();
  if (!facts.length) { const row = node("tr"); const cell = node("td", "", "尚无标准化事实。只有通过接口保存的真实来源行才会显示在这里。"); cell.colSpan = 6; row.append(cell); body.append(row); return; }
  facts.forEach((fact) => {
    const row = node("tr"); const concept = node("td"); concept.append(node("strong", "", fact.concept), node("small", "", fact.label_raw));
    const period = node("td", "", fact.period_end); const raw = node("td", "", `${fact.raw_value} ${fact.display_unit}`); const normalized = node("td", "", formatNumber(fact.normalized_value));
    const location = node("td"); location.append(node("strong", "", `第 ${fact.page_number} 页`), node("small", "", `${fact.section} · ${fact.column_label}`));
    const status = node("td"); status.append(chip(fact.validation_status)); row.append(concept, period, raw, normalized, location, status); body.append(row);
  });
}
function formatNumber(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(number) : String(value);
}
function metricValue(metric) {
  if (metric.value === null) return "—";
  const value = Number(metric.value);
  if (metric.unit === "ratio") return `${(value * 100).toFixed(2)}%`;
  if (metric.unit === "CNY") return `¥ ${new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 }).format(value)}`;
  return `${formatNumber(value)}${metric.unit === "multiple" ? "×" : ""}`;
}
function renderMetrics() {
  const target = $("#metric-grid"); target.replaceChildren(); const metrics = state.workspace.metrics;
  if (!metrics.length) return clearAndEmpty(target, "尚无计算结果。录入所需事实后运行确定性指标计算。");
  metrics.forEach((metric) => {
    const card = node("article", "metric-card"); card.dataset.state = metric.status;
    const header = node("header"); header.append(node("h3", "", metricLabels[metric.metric_code] ?? metric.metric_code), chip(metric.status));
    card.append(header, node("div", "metric-value", metricValue(metric)));
    if (metric.reason) card.append(node("p", "surface-note", metric.reason));
    const details = node("details"); const summary = node("summary", "", "公式版本与输入快照"); const pre = node("pre", "", `${metric.definition_version} / ${metric.calculator_version}\n${JSON.stringify(metric.input_snapshot, null, 2)}`); details.append(summary, pre); card.append(details); target.append(card);
  });
}
function renderRisks() {
  const target = $("#risk-list"); target.replaceChildren(); const risks = state.workspace.risks;
  if (!risks.length) return clearAndEmpty(target, "尚无风险发现。指标形成后运行确定性风险识别。");
  risks.forEach((risk) => {
    const card = node("article", "risk-card"); card.dataset.severity = risk.severity; const header = node("header"); header.append(node("h3", "", risk.title), chip(risk.severity));
    card.append(header, node("p", "", risk.description));
    if (risk.limitations.length) card.append(node("p", "surface-note", `限制：${risk.limitations.join("；")}`));
    card.append(node("footer", "", `${risk.category} · 置信度 ${(Number(risk.confidence) * 100).toFixed(0)}% · ${risk.risk_code}`)); target.append(card);
  });
}
function renderReport() {
  const target = $("#report-view"); target.replaceChildren(); const report = state.workspace.reports[0];
  if (!report) return clearAndEmpty(target, "尚无候选报告。报告只会从已持久化事实、指标、Claim、Evidence 和风险组装。");
  const heading = node("div"); heading.append(node("p", "overline", `${report.schema_version} · VERSION ${report.version}`), node("h2", "", `${state.workspace.run.company_name}年度报告分析`), chip(report.status)); target.append(heading);
  const content = report.content;
  appendReportSection(target, "财务事实", (content.facts ?? []).map((item) => `${item.label_raw}：${item.normalized_value ?? "—"} ${item.currency ?? ""}`));
  appendReportSection(target, "确定性计算", (content.calculations?.claims ?? []).map((item) => item.text));
  appendReportSection(target, "分析推断", (content.inferences ?? []).map((item) => item.text));
  appendReportSection(target, "风险提示", (content.risks ?? []).map((item) => `${item.title}：${item.description}`));
  const limitations = [...(content.limitations?.claims ?? []).map((item) => item.text), ...(content.limitations?.risk_limitations ?? []).map((item) => item.text)];
  appendReportSection(target, "限制与不确定性", limitations);
}
function appendReportSection(target, title, items) {
  const section = node("section", "report-section"); section.append(node("h3", "", title));
  if (!items.length) section.append(node("p", "empty-copy", "该分区没有持久化内容。")); else { const list = node("ul"); items.forEach((text) => list.append(node("li", "", text))); section.append(list); }
  target.append(section);
}
function renderEvaluation() {
  const target = $("#evaluation-view"); target.replaceChildren(); const evaluation = state.workspace.evaluations[0];
  if (!evaluation) return clearAndEmpty(target, "尚未对候选报告运行独立 Evaluator。");
  target.append(chip(evaluation.status), node("p", "surface-note", `${evaluation.evaluator_version} · ${formatDateTime(evaluation.created_at)}`));
  evaluation.checks.forEach((check) => { const row = node("div", "check-row"); row.dataset.result = check.result; row.append(node("span", "check-symbol", check.result === "passed" ? "✓" : "×")); const copy = node("div"); copy.append(node("strong", "", check.code), node("small", "", check.message ?? check.result)); row.append(copy); target.append(row); });
  if (evaluation.repair_instruction) target.append(node("div", "notice notice-warning", `修复建议：${evaluation.repair_instruction}`));
}
function renderGate() {
  const target = $("#gate-view"); target.replaceChildren(); const gate = state.workspace.gate_decisions[0];
  if (!gate) return clearAndEmpty(target, "Evaluator 完成后才能提交 Goal Gate。评测通过本身不会把运行标记为 verified。");
  const result = node("div", "gate-result"); result.append(node("strong", "", statusLabels[gate.decision] ?? gate.decision), node("p", "", gate.repair_instruction ?? "该判定已持久化且可审计。"), node("code", "", `${gate.gate_version} · ${compactId(gate.gate_id)}`)); target.append(result);
  gate.blocking_reasons.forEach((reason) => target.append(node("div", "notice notice-warning", `${reason.code ?? "blocking"}：${reason.message ?? "存在阻断项"}`)));
}
function renderCheckpoints() {
  const target = $("#checkpoint-list"); target.replaceChildren(); const checkpoints = state.workspace.checkpoints;
  if (!checkpoints.length) return clearAndEmpty(target, "尚无持久化恢复点。");
  checkpoints.forEach((checkpoint) => {
    const card = node("article", "checkpoint-card"); const copy = node("div"); copy.append(node("h3", "", `状态版本 ${checkpoint.state_version} · ${checkpoint.node}`));
    const meta = node("div", "checkpoint-meta"); meta.append(node("span", "", formatDateTime(checkpoint.created_at)), node("span", "", `来源 ${checkpoint.source_ids.length}`), node("span", "", `事实 ${checkpoint.fact_ids.length}`), node("span", "", `指标 ${checkpoint.metric_ids.length}`), node("span", "", `Claim ${checkpoint.claim_ids.length}`)); copy.append(meta);
    const button = node("button", "button button-secondary", "恢复到此处"); button.type = "button"; button.dataset.restore = checkpoint.checkpoint_id; card.append(copy, button); target.append(card);
  });
}

async function refreshEvidence() {
  if (!state.runId) return;
  const target = $("#claim-list");
  try {
    const view = await requestJson(`${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/evidence-view`, { headers: headers() }, "无法读取报告证据。");
    renderEvidence(view);
  } catch (error) { clearAndEmpty(target, error instanceof Error ? error.message : "无法读取报告证据。"); clearAndEmpty($("#evidence-detail"), "请选择有可定位来源的结论。"); }
}
function renderEvidence(view) {
  const list = $("#claim-list"); list.replaceChildren(); clearPdf();
  if (!view.claims.length) return clearAndEmpty(list, "报告中没有可显示的 Claim。");
  view.claims.forEach((claim, index) => {
    const button = node("button", `claim-button${index === 0 ? " is-active" : ""}`); button.type = "button"; button.append(node("span", "", claim.text), node("small", "", `${claimTypeLabels[claim.claim_type] ?? claim.claim_type} · ${claim.locator_status}`));
    button.addEventListener("click", () => { $$(".claim-button").forEach((item) => item.classList.remove("is-active")); button.classList.add("is-active"); renderEvidenceDetail(claim); }); list.append(button); if (index === 0) renderEvidenceDetail(claim);
  });
}
function renderEvidenceDetail(claim) {
  const target = $("#evidence-detail"); target.replaceChildren(); clearPdf();
  target.append(node("p", "", claim.text), chip(claim.status));
  if (!claim.evidence.length) return target.append(node("div", "notice notice-warning", locatorReasons[claim.unavailable_reason] ?? "没有关联 Evidence。"));
  claim.evidence.forEach((evidence) => {
    const card = node("div", "evidence-card"); card.append(node("strong", "", `${evidence.evidence_type} · ${evidence.supports}`));
    if (evidence.excerpt) card.append(node("p", "", evidence.excerpt));
    if (!evidence.source_pages.length) card.append(node("p", "surface-note", locatorReasons[evidence.unavailable_reason] ?? "无 PDF 页级定位。"));
    evidence.source_pages.forEach((source) => {
      const button = node("button", "evidence-source", source.status === "available" ? `${source.file_name} · 第 ${source.page_number} 页` : (locatorReasons[source.unavailable_reason] ?? "来源不可用"));
      button.type = "button"; button.disabled = source.status !== "available"; if (!button.disabled) button.addEventListener("click", () => openPdfPage(source)); card.append(button);
      if (source.excerpt) card.append(node("p", "surface-note", source.excerpt));
    }); target.append(card);
  });
}
async function openPdfPage(source) {
  try {
    const response = await fetch(source.content_url, { headers: headers() });
    if (!response.ok) { let body = null; try { body = await response.json(); } catch { /* fallback */ } throw new Error(explainApiError(body, "PDF 读取失败。")); }
    clearPdf(); state.pdfObjectUrl = URL.createObjectURL(await response.blob()); $("#pdf-frame").src = `${state.pdfObjectUrl}#page=${source.page_number}`; $("#pdf-wrap").hidden = false;
  } catch (error) { showToast(error instanceof Error ? error.message : "PDF 读取失败。", "bad"); }
}
function clearPdf() {
  if (state.pdfObjectUrl) URL.revokeObjectURL(state.pdfObjectUrl);
  state.pdfObjectUrl = null; $("#pdf-frame").removeAttribute("src"); $("#pdf-wrap").hidden = true;
}

async function runAction(action) {
  if (!state.workspace) return;
  if (action === "facts") return activateTab("facts");
  if (action === "attach") return attachDocument();
  const runId = encodeURIComponent(state.runId); const period_end = state.workspace.run.report_period_end; const source = state.workspace.sources[0]; const report = state.workspace.reports[0];
  const operations = {
    parse: [`${API_BASE}/analysis-runs/${runId}/documents/${encodeURIComponent(source?.source_id)}/parse`, null, "PDF 页面解析完成。"],
    statements: [`${API_BASE}/analysis-runs/${runId}/documents/${encodeURIComponent(source?.source_id)}/statements`, null, "三张报表识别完成。"],
    metrics: [`${API_BASE}/analysis-runs/${runId}/metrics/calculate`, { period_end }, "指标计算完成。"],
    analysis: [`${API_BASE}/analysis-runs/${runId}/financial-analysis`, { period_end }, "财务结论已持久化。"],
    risks: [`${API_BASE}/analysis-runs/${runId}/risk-detection`, { period_end }, "风险结果已持久化。"],
    report: [`${API_BASE}/analysis-runs/${runId}/reports`, { period_end }, "候选报告已生成。"],
    evaluate: [`${API_BASE}/analysis-runs/${runId}/evaluations`, { report_id: report?.report_id }, "独立评测完成。"],
    gate: [`${API_BASE}/analysis-runs/${runId}/goal-gate`, { report_id: report?.report_id }, "Goal Gate 判定已持久化。"],
  };
  const operation = operations[action]; if (!operation) return;
  setActionBusy(true);
  try {
    const options = { method: "POST", headers: headers() };
    if (operation[1]) { options.headers = headers({ "Content-Type": "application/json" }); options.body = JSON.stringify(operation[1]); }
    await requestJson(operation[0], options, `${operation[2]}操作未完成。`); showToast(operation[2]); await Promise.all([refreshWorkspace(), refreshProgress(), refreshEvents()]);
    if (["report", "evaluate", "gate"].includes(action)) activateTab(action === "report" ? "report" : "evaluation");
  } catch (error) { const message = error instanceof Error ? error.message : "操作失败。"; setWorkspaceMessage(message, "error"); showToast(message, "bad"); }
  finally { setActionBusy(false); }
}
function setActionBusy(busy) { $$('[data-action]').forEach((button) => { button.disabled = busy || !isActionReady(button.dataset.action); }); }
async function attachDocument() {
  const input = $("#attach-file"); if (!input?.files?.[0]) { input?.click(); showToast("请选择需要上传的 PDF。", "bad"); return; }
  const formData = new FormData(); formData.append("file", input.files[0], input.files[0].name);
  try { await requestJson(`${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/documents`, { method: "POST", headers: headers(), body: formData }, "PDF 上传未完成。"); showToast("PDF 已上传。"); await refreshWorkspace(); } catch (error) { showToast(error instanceof Error ? error.message : "PDF 上传失败。", "bad"); }
}
async function submitFact(event) {
  event.preventDefault(); if (!event.currentTarget.reportValidity() || !state.workspace) return;
  const values = new FormData(event.currentTarget); const statement = state.workspace.statements.find((item) => item.statement_type === values.get("statement_type"));
  const periodType = String(values.get("period_type"));
  const payload = {
    statement_type: String(values.get("statement_type")), raw_label: String(values.get("raw_label")).trim(), raw_value: String(values.get("raw_value")).trim(),
    period_start: periodType === "duration" ? String(values.get("period_start")) : null, period_end: String(values.get("period_end")), period_type: periodType,
    scope: "consolidated", currency: "CNY", display_unit: String(values.get("display_unit")), sign_convention: "reported-sign-v1",
    page_number: Number(values.get("page_number")), section: String(values.get("section")).trim(), table_id: statement?.table_id ?? null,
    row_label: String(values.get("raw_label")).trim(), column_label: String(values.get("column_label")).trim(), bbox: null,
    extraction_method: "manual", confidence: String(values.get("confidence")),
  };
  try {
    await requestJson(`${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/documents/${encodeURIComponent(values.get("source_id"))}/facts/normalize`, { method: "POST", headers: headers({ "Content-Type": "application/json" }), body: JSON.stringify(payload) }, "事实保存失败。");
    showToast("标准化事实已保存。", "good"); event.currentTarget.elements.raw_label.value = ""; event.currentTarget.elements.raw_value.value = ""; await refreshWorkspace();
  } catch (error) { showToast(error instanceof Error ? error.message : "事实保存失败。", "bad"); }
}
async function restoreCheckpoint(checkpointId) {
  try { await requestJson(`${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/checkpoints/${encodeURIComponent(checkpointId)}/restore`, { method: "POST", headers: headers() }, "Checkpoint 恢复失败。"); showToast("Checkpoint 已校验并恢复。"); await Promise.all([refreshWorkspace(), refreshProgress(), refreshEvents()]); }
  catch (error) { showToast(error instanceof Error ? error.message : "Checkpoint 恢复失败。", "bad"); }
}

function activateTab(name) {
  $$(".tab").forEach((item) => item.classList.toggle("is-active", item.dataset.tab === name));
  $$(".tab-panel").forEach((item) => item.classList.toggle("is-active", item.dataset.panel === name));
  if (name === "report") refreshEvidence();
}
function openCreateDialog() {
  if (!state.userId) { $("#user-id").focus(); showToast("请先输入本地用户标识。", "bad"); return; }
  $("#create-dialog").showModal();
}
async function submitAnalysis(event) {
  event.preventDefault(); if (!event.currentTarget.reportValidity()) return;
  const values = new FormData(event.currentTarget); const button = $("#submit-button"); const message = $("#form-message");
  button.disabled = true; button.textContent = "正在创建…"; message.textContent = "正在创建服务端运行。"; message.className = "form-message";
  try {
    const run = await requestJson(`${API_BASE}/analysis-runs`, { method: "POST", headers: headers({ "Content-Type": "application/json", "Idempotency-Key": makeIdempotencyKey() }), body: JSON.stringify({ company_name: String(values.get("company_name")).trim(), security_code: String(values.get("security_code")).trim(), report_period_end: String(values.get("report_period_end")), analysis_focus: [String(values.get("analysis_focus"))] }) }, "分析运行创建失败。");
    state.runId = run.run_id; message.textContent = "运行已创建，正在上传 PDF。"; const upload = new FormData(); const file = values.get("file"); upload.append("file", file, file.name);
    await requestJson(`${API_BASE}/analysis-runs/${encodeURIComponent(run.run_id)}/documents`, { method: "POST", headers: headers(), body: upload }, "PDF 上传失败。");
    message.textContent = "运行和来源文件已创建。"; message.className = "form-message success"; await loadRuns(); $("#create-dialog").close(); event.currentTarget.reset(); await selectRun(run.run_id); showToast("分析任务已创建，下一步可解析 PDF。");
  } catch (error) { message.textContent = error instanceof Error ? error.message : "创建失败。"; message.className = "form-message error"; }
  finally { button.disabled = false; button.textContent = "创建并上传"; }
}

$("#identity-form").addEventListener("submit", async (event) => {
  event.preventDefault(); state.userId = $("#user-id").value.trim(); state.runId = null; state.workspace = null; $("#workspace-view").hidden = true; $("#welcome-view").hidden = false;
  try { await loadRuns(true); if (!state.runs.length) showToast("该用户暂无任务，可以新建分析。"); } catch (error) { showToast(error instanceof Error ? error.message : "任务载入失败。", "bad"); }
});
$("#refresh-runs").addEventListener("click", () => loadRuns().catch((error) => showToast(error.message, "bad")));
$("#refresh-workspace").addEventListener("click", async () => { try { await Promise.all([refreshWorkspace(), refreshProgress(), refreshEvents()]); showToast("工作台已刷新。"); } catch (error) { showToast(error.message, "bad"); } });
$("#open-create").addEventListener("click", openCreateDialog); $$('[data-open-create]').forEach((button) => button.addEventListener("click", openCreateDialog));
$("#close-create").addEventListener("click", () => $("#create-dialog").close()); $("#cancel-create").addEventListener("click", () => $("#create-dialog").close());
$("#analysis-form").addEventListener("submit", submitAnalysis); $("#fact-form").addEventListener("submit", submitFact);
$("#fact-period-type").addEventListener("change", (event) => { const duration = event.target.value === "duration"; $("#period-start-field").hidden = !duration; $("#fact-period-start").required = duration; });
$("#refresh-evidence").addEventListener("click", refreshEvidence); $$(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
document.addEventListener("click", (event) => { const action = event.target.closest("[data-action]")?.dataset.action; if (action) runAction(action); const checkpoint = event.target.closest("[data-restore]")?.dataset.restore; if (checkpoint) { state.pendingCheckpoint = checkpoint; $("#confirm-copy").textContent = `将恢复 ${compactId(checkpoint)} 的控制状态。恢复前会执行完整性校验。`; $("#confirm-dialog").showModal(); } });
$("#confirm-restore").addEventListener("click", async (event) => { event.preventDefault(); $("#confirm-dialog").close(); if (state.pendingCheckpoint) await restoreCheckpoint(state.pendingCheckpoint); state.pendingCheckpoint = null; });
$("#report-period-end").max = new Date().toISOString().slice(0, 10);
