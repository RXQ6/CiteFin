const API_BASE = "/api/v1";

const form = document.querySelector("#analysis-form");
const submitButton = document.querySelector("#submit-button");
const formMessage = document.querySelector("#form-message");
const runPanel = document.querySelector("#run-panel");
const runMessage = document.querySelector("#run-message");
const runStatusBadge = document.querySelector("#run-status-badge");
const runCompany = document.querySelector("#run-company");
const runId = document.querySelector("#run-id");
const runNode = document.querySelector("#run-node");
const runUpdated = document.querySelector("#run-updated");
const taskCount = document.querySelector("#task-count");
const taskList = document.querySelector("#task-list");
const errorList = document.querySelector("#error-list");
const eventList = document.querySelector("#event-list");
const reportPeriodEnd = document.querySelector("#report-period-end");

const state = {
  runId: null,
  userId: null,
  lastEventId: null,
  events: [],
  refreshTimer: null,
};

const errorLabels = {
  analysis_run_not_found: "找不到该分析运行",
  database_not_configured: "服务端尚未配置数据库",
  file_too_large: "文件超过大小限制",
  invalid_pdf: "文件不是有效 PDF",
  pdf_encrypted: "PDF 已加密",
  pdf_not_searchable: "PDF 不可检索",
  source_document_not_found: "找不到源文件",
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
};

function setFormMessage(message, kind = "") {
  formMessage.textContent = message;
  formMessage.className = `form-message ${kind}`.trim();
}

function setRunMessage(message, kind = "notice-info") {
  runMessage.textContent = message;
  runMessage.className = `notice ${kind}`;
}

function setBusy(isBusy) {
  submitButton.disabled = isBusy;
  submitButton.textContent = isBusy ? "正在创建并上传…" : "创建并上传报告";
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}

function explainApiError(body, fallback) {
  const detail = body?.detail;
  if (detail && typeof detail === "object") {
    const code = typeof detail.code === "string" ? detail.code : "request_failed";
    const label = errorLabels[code] ?? "请求未完成";
    const message = typeof detail.message === "string" ? detail.message : "请检查输入后重试。";
    return `${label}（${code}）：${message}`;
  }
  if (typeof detail === "string") return detail;
  return fallback;
}

async function requestJson(url, options, fallback) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("无法连接到服务端，请确认 API 正在运行。", { cause: "network" });
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    // A non-JSON response is handled by the stable fallback below.
  }
  if (!response.ok) {
    throw new Error(explainApiError(body, fallback));
  }
  return body;
}

function apiHeaders(userId, extra = {}) {
  return { "X-User-ID": userId, ...extra };
}

function makeIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return `frontend-${crypto.randomUUID()}`;
  return `frontend-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function showRun(run) {
  state.runId = run.run_id;
  runPanel.hidden = false;
  runCompany.textContent = `${run.company_name} · ${run.security_code}`;
  runId.textContent = run.run_id;
  runNode.textContent = run.current_node || "—";
  runUpdated.textContent = formatDateTime(run.created_at);
  updateStatus(run.status);
  runPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function updateStatus(status) {
  const value = status || "unknown";
  runStatusBadge.textContent = statusLabels[value] ?? value;
  runStatusBadge.className = `status-badge status-${value}`;
}

function renderProgress(progress) {
  updateStatus(progress.status);
  runNode.textContent = progress.current_node || "—";
  runUpdated.textContent = formatDateTime(progress.updated_at);
  taskCount.textContent = `${progress.tasks.length} 个任务`;

  taskList.replaceChildren();
  if (progress.tasks.length === 0) {
    appendEmpty(taskList, "服务端暂未返回任务。");
  } else {
    progress.tasks.forEach((task) => {
      const item = document.createElement("li");
      item.className = "task-item";
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = task.title;
      const metadata = document.createElement("small");
      metadata.textContent = `${task.feature_id} · ${task.task_type} · 尝试 ${task.attempt_count}`;
      content.append(title, metadata);
      const stateBadge = document.createElement("span");
      stateBadge.className = "task-state";
      stateBadge.textContent = task.status;
      item.append(content, stateBadge);
      taskList.append(item);
    });
  }

  errorList.replaceChildren();
  if (progress.recent_errors.length === 0) {
    appendEmpty(errorList, "暂无服务端错误。");
  } else {
    progress.recent_errors.forEach((error) => {
      const item = document.createElement("li");
      item.className = "error-item";
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = `${error.code} · ${error.event_type}`;
      const metadata = document.createElement("small");
      metadata.textContent = `${error.node} · ${formatDateTime(error.created_at)}`;
      content.append(title, metadata);
      item.append(content);
      errorList.append(item);
    });
  }

  const terminalStatuses = ["verified", "failed", "blocked", "revision_required"];
  if (terminalStatuses.includes(progress.status)) {
    setRunMessage(`服务端状态：${statusLabels[progress.status] ?? progress.status}。`,
      progress.status === "verified" ? "notice-success" : "notice-info");
  } else {
    setRunMessage("状态来自服务端进度接口，页面不本地推算运行状态。", "notice-info");
  }
}

function appendEmpty(list, message) {
  const item = document.createElement("li");
  item.className = "empty-state";
  item.textContent = message;
  list.append(item);
}

async function refreshProgress() {
  if (!state.runId || !state.userId) return;
  const progress = await requestJson(
    `${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/progress`,
    { headers: apiHeaders(state.userId) },
    "无法读取运行进度。",
  );
  renderProgress(progress);
}

function parseEventStream(body) {
  return body
    .split("\n\n")
    .map((frame) => frame.trim())
    .filter(Boolean)
    .map((frame) => {
      const idLine = frame.split("\n").find((line) => line.startsWith("id: "));
      const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
      if (!idLine || !dataLine) return null;
      try {
        return { id: idLine.slice(4), data: JSON.parse(dataLine.slice(6)) };
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

function renderEvents() {
  eventList.replaceChildren();
  if (state.events.length === 0) {
    appendEmpty(eventList, "尚未收到事件。");
    return;
  }
  state.events.forEach((event) => {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${event.data.event_type} · ${event.data.status}`;
    const time = document.createElement("time");
    time.textContent = formatDateTime(event.data.created_at);
    const id = document.createElement("code");
    id.textContent = event.id;
    item.append(title, time, id);
    eventList.append(item);
  });
}

async function refreshEvents() {
  if (!state.runId || !state.userId) return;
  const query = new URLSearchParams({ limit: "100" });
  if (state.lastEventId) query.set("after", state.lastEventId);
  const response = await fetch(
    `${API_BASE}/analysis-runs/${encodeURIComponent(state.runId)}/events?${query}`,
    { headers: apiHeaders(state.userId) },
  );
  if (!response.ok) return;
  const frames = parseEventStream(await response.text());
  frames.forEach((event) => {
    if (!state.events.some((known) => known.id === event.id)) state.events.push(event);
    state.lastEventId = event.id;
  });
  renderEvents();
}

function startRefreshLoop() {
  if (state.refreshTimer) window.clearInterval(state.refreshTimer);
  state.refreshTimer = window.setInterval(async () => {
    try {
      await Promise.all([refreshProgress(), refreshEvents()]);
    } catch (error) {
      setRunMessage(error instanceof Error ? error.message : "读取服务端状态失败。", "notice-error");
    }
  }, 3000);
}

async function uploadDocument(run) {
  const fileInput = document.querySelector("#report-file");
  const file = fileInput.files?.[0];
  if (!file) throw new Error("请选择要上传的年度报告 PDF。", { cause: "input" });

  const formData = new FormData();
  formData.append("file", file, file.name);
  return requestJson(
    `${API_BASE}/analysis-runs/${encodeURIComponent(run.run_id)}/documents`,
    { method: "POST", headers: apiHeaders(state.userId), body: formData },
    "PDF 上传未完成。",
  );
}

async function submitAnalysis(event) {
  event.preventDefault();
  if (!form.reportValidity()) return;

  const formData = new FormData(form);
  const userId = String(formData.get("user_id")).trim();
  const runRequest = {
    company_name: String(formData.get("company_name")).trim(),
    security_code: String(formData.get("security_code")).trim(),
    report_period_end: String(formData.get("report_period_end")),
    analysis_focus: [String(formData.get("analysis_focus"))],
  };

  state.userId = userId;
  state.lastEventId = null;
  state.events = [];
  setBusy(true);
  setFormMessage("正在创建服务端分析运行…");
  try {
    const run = await requestJson(
      `${API_BASE}/analysis-runs`,
      {
        method: "POST",
        headers: apiHeaders(userId, {
          "Content-Type": "application/json",
          "Idempotency-Key": makeIdempotencyKey(),
        }),
        body: JSON.stringify(runRequest),
      },
      "分析运行创建未完成。",
    );
    showRun(run);
    setFormMessage("运行已创建，正在上传 PDF…");
    await uploadDocument(run);
    setFormMessage("运行已创建且 PDF 已上传。", "success");
    await Promise.all([refreshProgress(), refreshEvents()]);
    startRefreshLoop();
  } catch (error) {
    const message = error instanceof Error ? error.message : "请求未完成，请重试。";
    setFormMessage(message, "error");
    if (state.runId) setRunMessage(message, "notice-error");
  } finally {
    setBusy(false);
  }
}

reportPeriodEnd.max = new Date().toISOString().slice(0, 10);
form.addEventListener("submit", submitAnalysis);
