import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Metric = {
  code: string;
  label: string;
  category: string;
  display_value: string;
  chart_value: number;
  unit_label: string;
  status: string;
};
type Evidence = { page: number; section: string; snippet: string };
type Claim = { claim_id: string; type: string; text: string; evidence: Evidence[] };
type VisualizationSpec = {
  visualization_id: string;
  chart_key: string;
  spec_version: string;
  chart_type: "bar" | "grouped_bar";
  title: string;
  question: string;
  dataset: {
    dimensions: string[];
    measures: string[];
    rows: Array<Record<string, unknown>>;
    source_refs: Array<Record<string, unknown>>;
  };
  encoding: {
    x_field: string;
    y_field: string;
    series_field: string | null;
    unit: string;
    value_format: "percent" | "currency_100m" | "integer";
    display_scale: string;
  };
  evidence_ids: string[];
  limitations: string[];
  data_snapshot_hash: string;
  renderer_version: string;
  status: "validated" | "invalid";
};
type Demo = {
  schema_version: string;
  synthetic: boolean;
  notice: string;
  company: { name: string; security_code: string; report_period_end: string; status: string };
  summary: Record<string, string | number> & { headline: string };
  metrics: Metric[];
  visualizations: VisualizationSpec[];
  risks: Array<{ severity: string; title: string; description: string; basis: string; limitations: string[]; evidence_claim_id: string }>;
  claims: Claim[];
  report: { sections: Array<{ title: string; paragraphs: string[] }> };
  evidence_document: { file_name: string; page_count: number; content_url: string };
  audit: Record<string, string | number>;
};

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: 1 } } });
const metricCategories = ["增长", "盈利", "偿债", "现金流", "经营质量"];

function ArrowIcon() {
  return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 4 6 6-6 6M3 10h10" /></svg>;
}
function ShieldIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4.5 6v5.6c0 4.6 3.2 7.8 7.5 9.4 4.3-1.6 7.5-4.8 7.5-9.4V6L12 3Z" /><path d="m9 12 2 2 4-5" /></svg>;
}
function QuoteIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17h4V9H5v5c0 1.7.7 3 2 3Zm10 0h4V9h-6v5c0 1.7.7 3 2 3Z" /></svg>;
}

async function getDemo(): Promise<Demo> {
  const response = await fetch("/api/v1/demo/workspace");
  if (!response.ok) throw new Error("示例报告暂时无法载入，请稍后重试。");
  return response.json() as Promise<Demo>;
}

function Brand() {
  return <button className="brand" type="button" onClick={() => location.assign("/")} aria-label="返回 CiteFin 首页"><span>CF</span><strong>CiteFin</strong></button>;
}

function Header({ onDemo, onUpload }: { onDemo: () => void; onUpload: () => void }) {
  return <header className="site-header"><Brand /><nav aria-label="主导航"><button onClick={onDemo}>示例报告</button><a href="#capabilities">产品能力</a><a href="#method">工作方式</a></nav><div className="header-actions"><button className="button ghost" onClick={onUpload}>登录</button><button className="button primary small" onClick={onUpload}>上传年报</button></div></header>;
}

function Landing({ onDemo, onUpload }: { onDemo: () => void; onUpload: () => void }) {
  return <>
    <Header onDemo={onDemo} onUpload={onUpload} />
    <main>
      <section className="hero">
        <div className="hero-copy"><p className="eyebrow"><span /> 证据驱动的财报研究</p><h1>看懂一份年报，<br /><em>不必相信黑箱。</em></h1><p className="hero-lead">上传年度报告，获得可复算指标、结构化风险和逐页证据。每个重要数字，都能回到原文核验。</p><div className="hero-actions"><button className="button primary" onClick={onDemo}>查看示例报告 <ArrowIcon /></button><button className="button secondary" onClick={onUpload}>上传年报分析</button></div><div className="trust-row"><span><ShieldIcon />不执行交易</span><span>确定性计算</span><span>重大结论 100% 证据覆盖</span></div></div>
        <div className="hero-preview" aria-label="示例分析概览"><div className="preview-top"><div><small>合成案例 · 600001</small><h2>华岳制造</h2></div><span className="status good">合成案例已验证</span></div><div className="preview-callout"><small>核心结论</small><p>收入与利润同步增长，现金流覆盖盈利，偿债结构保持稳健。</p></div><div className="preview-metrics"><div><span>营收增长</span><strong>+20.0%</strong><small>同比</small></div><div><span>净资产收益率</span><strong>16.0%</strong><small>ROE</small></div><div><span>经营现金流</span><strong>1.50亿</strong><small>覆盖利润 1.25×</small></div></div><div className="evidence-line"><QuoteIcon /><div><strong>结论已关联原始证据</strong><span>合并利润表 · 第 2 页</span></div><b>→</b></div></div>
      </section>
      <section className="proof-strip"><span>一份年报</span><b>→</b><span>23 项标准化事实</span><b>→</b><span>15 项核心指标</span><b>→</b><span>可定位分析报告</span></section>
      <section id="capabilities" className="section"><div className="section-heading"><p className="eyebrow">研究结果，而不是数据堆砌</p><h2>重要信息，一眼看清。</h2><p>普通用户先看到结论；需要复核时，再逐层展开公式、事实和原始 PDF。</p></div><div className="feature-grid"><article><span className="feature-number">01</span><h3>财务指标</h3><p>增长、盈利、偿债、现金流和经营质量分组呈现，公式与输入值随时可查。</p><div className="mini-bars"><i style={{height:"48%"}} /><i style={{height:"64%"}} /><i style={{height:"56%"}} /><i style={{height:"82%"}} /><i style={{height:"91%"}} /></div></article><article><span className="feature-number">02</span><h3>风险提示</h3><p>区分风险等级、判断依据和数据限制，不用模糊措辞制造确定感。</p><div className="risk-sample"><span>观察</span><b>应收增速高于收入</b><small>点击查看规则与证据</small></div></article><article><span className="feature-number">03</span><h3>证据定位</h3><p>结论、指标、事实和 PDF 页码形成完整链路，点击即可回到来源。</p><div className="evidence-sample"><span>结论</span><i /> <span>指标</span><i /> <span>PDF · P2</span></div></article></div></section>
      <section id="method" className="section method"><div><p className="eyebrow">三步完成研究</p><h2>把复杂流程留给系统。</h2></div><ol><li><span>1</span><div><h3>上传与确认</h3><p>上传中文可检索年报，确认公司与报告期。</p></div></li><li><span>2</span><div><h3>自动分析</h3><p>解析、标准化、计算和风险识别自动执行，仅在歧义处请求确认。</p></div></li><li><span>3</span><div><h3>核验与导出</h3><p>阅读报告，点击证据核验，并导出带风险声明的研究材料。</p></div></li></ol></section>
      <section className="final-cta"><p className="eyebrow">先看结果，再决定是否上传</p><h2>用一份完整示例，了解 CiteFin。</h2><button className="button inverse" onClick={onDemo}>打开合成示例报告 <ArrowIcon /></button></section>
    </main><Footer />
  </>;
}

function formattedChartValue(value: number, format: VisualizationSpec["encoding"]["value_format"]) {
  if (format === "percent") return `${value.toFixed(1)}%`;
  if (format === "currency_100m") return `${value.toFixed(2)} 亿元`;
  return Math.round(value).toLocaleString("zh-CN");
}

function FinancialChart({ spec }: { spec: VisualizationSpec }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    let disposed = false;
    let chart: { resize: () => void; dispose: () => void } | undefined;
    const { rows } = spec.dataset;
    const { x_field: xField, y_field: yField, series_field: seriesField, value_format: valueFormat } = spec.encoding;
    const categories = Array.from(new Set(rows.map((row) => String(row[xField]))));
    const seriesNames = seriesField
      ? Array.from(new Set(rows.map((row) => String(row[seriesField]))))
      : [spec.title];
    const scale = Number(spec.encoding.display_scale);
    const chartValue = (raw: unknown) => {
      const value = Number(raw);
      if (valueFormat === "percent") return value * 100;
      return value / scale;
    };
    void Promise.all([
      import("echarts/core"),
      import("echarts/charts"),
      import("echarts/components"),
      import("echarts/renderers"),
    ]).then(([core, charts, components, renderers]) => {
      if (disposed || !element.current) return;
      core.use([charts.BarChart, components.GridComponent, components.TooltipComponent, components.LegendComponent, components.AriaComponent, renderers.SVGRenderer]);
      const instance = core.init(element.current, undefined, { renderer: "svg" });
      const palette = ["#2f8762", "#d39b2c", "#d66a4e", "#64748b", "#8b5cf6"];
      instance.setOption({
        aria: { enabled: true, decal: { show: true } },
        animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        color: palette,
        grid: { left: 56, right: 20, top: seriesField ? 46 : 20, bottom: 62 },
        legend: { show: Boolean(seriesField), top: 2, textStyle: { color: "#44534b" } },
        tooltip: {
          trigger: "axis",
          valueFormatter: (value: number) => formattedChartValue(value, valueFormat),
        },
        xAxis: {
          type: "category",
          data: categories,
          axisLabel: { color: "#617168", interval: 0, formatter: (value: string) => value.length > 8 ? `${value.slice(0, 8)}…` : value },
          axisLine: { lineStyle: { color: "#aeb9b3" } },
        },
        yAxis: {
          type: "value",
          min: 0,
          minInterval: valueFormat === "integer" ? 1 : undefined,
          axisLabel: { formatter: (value: number) => formattedChartValue(value, valueFormat), color: "#617168" },
          splitLine: { lineStyle: { color: "#e7ece8" } },
        },
        series: seriesNames.map((name, index) => ({
          name,
          type: "bar",
          data: categories.map((category) => {
            const row = rows.find((item) => String(item[xField]) === category && (!seriesField || String(item[seriesField]) === name));
            return row ? chartValue(row[yField]) : null;
          }),
          barMaxWidth: 34,
          itemStyle: { color: palette[index % palette.length], borderRadius: [5, 5, 0, 0] },
        })),
      });
      chart = instance;
    });
    const resize = () => chart?.resize(); window.addEventListener("resize", resize);
    return () => { disposed = true; window.removeEventListener("resize", resize); chart?.dispose(); };
  }, [spec]);
  const downloadSvg = () => {
    const svg = element.current?.querySelector("svg");
    if (!svg) return;
    const blob = new Blob([svg.outerHTML], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${spec.chart_key}.svg`;
    link.click();
    URL.revokeObjectURL(url);
  };
  const xField = spec.encoding.x_field;
  const yField = spec.encoding.y_field;
  const seriesField = spec.encoding.series_field;
  return <figure className="financial-chart" aria-labelledby={`${spec.visualization_id}-title`}>
    <figcaption className="chart-heading"><div><h3 id={`${spec.visualization_id}-title`}>{spec.title}</h3><p>{spec.question}</p></div><button className="text-link" type="button" onClick={downloadSvg}>下载 SVG</button></figcaption>
    <div className="metric-chart" ref={element} role="img" aria-label={`${spec.title}。${spec.question}`} />
    <details className="chart-data"><summary>查看图表数据与来源</summary><div className="table-scroll"><table><thead><tr><th>{xField}</th>{seriesField && <th>{seriesField}</th>}<th>值</th></tr></thead><tbody>{spec.dataset.rows.map((row, index) => <tr key={`${String(row[xField])}-${index}`}><td>{String(row[xField])}</td>{seriesField && <td>{String(row[seriesField])}</td>}<td>{String(row[yField])} {spec.encoding.unit}</td></tr>)}</tbody></table></div><p>数据快照：{spec.data_snapshot_hash.slice(0, 12)}… · {spec.renderer_version}</p>{spec.limitations.map((limitation) => <p key={limitation}>限制：{limitation}</p>)}</details>
  </figure>;
}

function DemoPage({ onBack, onUpload }: { onBack: () => void; onUpload: () => void }) {
  const [tab, setTab] = useState("overview");
  const [claim, setClaim] = useState<Claim | null>(null);
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["public-demo"], queryFn: getDemo });
  if (isLoading) return <div className="loading-page"><Brand /><div className="skeleton wide" /><div className="skeleton" /><div className="skeleton" /></div>;
  if (error || !data) return <div className="error-page"><Brand /><h1>示例报告暂时无法打开</h1><p>{error instanceof Error ? error.message : "服务暂不可用"}</p><button className="button primary" onClick={() => refetch()}>重新加载</button></div>;
  const keyMetrics = data.metrics.filter((metric) => ["revenue_growth", "net_profit_growth", "roe", "ocf_to_net_profit", "debt_to_assets", "free_cash_flow"].includes(metric.code));
  return <div className="report-shell">
    <aside className="report-sidebar"><Brand /><div className="sidebar-label">公开示例</div><button className="side-link active">分析报告</button><button className="side-link" onClick={onUpload}>上传年报</button><button className="side-link" onClick={onBack}>返回首页</button><div className="sidebar-boundary"><ShieldIcon /><p>辅助研究，不构成投资建议，不执行任何交易。</p></div></aside>
    <main className="report-main"><div className="demo-notice"><strong>合成示例</strong><span>{data.notice}</span></div><header className="report-header"><div><p className="eyebrow">{data.company.security_code} · 年度报告分析</p><h1>{data.company.name}</h1><p>报告期 {data.company.report_period_end}</p></div><div className="report-header-actions"><span className="status good">合成案例已验证</span><button className="button secondary" onClick={() => window.print()}>导出预览</button><button className="button primary small" onClick={onUpload}>分析我的年报</button></div></header>
      <nav className="report-tabs" aria-label="报告内容">{[["overview","概览"],["metrics","财务指标"],["risks","风险"],["report","报告与证据"],["audit","高级审计"]].map(([id,label]) => <button key={id} className={tab===id?"active":""} onClick={() => setTab(id)}>{label}</button>)}</nav>
      {tab === "overview" && <section className="report-panel"><article className="headline-card"><div><p className="eyebrow">核心结论</p><h2>{data.summary.headline}</h2></div><div className="confidence"><strong>{data.summary.evidence_coverage}</strong><span>重大结论证据覆盖</span></div></article><div className="kpi-grid">{keyMetrics.map((metric) => <article key={metric.code}><span>{metric.label}</span><strong>{metric.display_value}</strong><small>{metric.unit_label} · 已计算</small></article>)}</div><div className="visualization-grid">{data.visualizations.filter((spec) => spec.chart_key !== "risk_distribution").map((spec) => <FinancialChart key={spec.visualization_id} spec={spec} />)}</div><div className="overview-columns"><article className="content-card"><div className="card-title"><div><p className="eyebrow">风险观察</p><h2>1 项观察</h2></div></div>{data.risks.map((risk) => <button className="risk-row" key={risk.title} onClick={() => setTab("risks")}><span>观察</span><div><strong>{risk.title}</strong><small>{risk.description}</small></div><b>→</b></button>)}<div className="positive-note"><ShieldIcon /><span>未触发高等级确定性风险规则</span></div></article></div></section>}
      {tab === "metrics" && <section className="report-panel"><div className="panel-intro"><div><p className="eyebrow">15 项确定性计算</p><h2>财务指标</h2></div><p>所有结果由版本化公式计算，不由模型自由生成。</p></div>{metricCategories.map((category) => <div className="metric-section" key={category}><h3>{category}</h3><div className="metric-list">{data.metrics.filter((metric) => metric.category === category).map((metric) => <article key={metric.code}><div><span>{metric.label}</span><small>{metric.code}</small></div><strong>{metric.display_value}</strong><span className="verified-dot">已计算</span></article>)}</div></div>)}</section>}
      {tab === "risks" && <section className="report-panel"><div className="panel-intro"><div><p className="eyebrow">规则、证据与限制</p><h2>风险与观察</h2></div><p>风险只在有确定事实或指标支撑时展示。</p></div>{data.visualizations.filter((spec) => spec.chart_key === "risk_distribution").map((spec) => <FinancialChart key={spec.visualization_id} spec={spec} />)}{data.risks.map((risk) => <article className="risk-detail" key={risk.title}><div className="risk-level">观察</div><div><h3>{risk.title}</h3><p>{risk.description}</p><dl><dt>判断依据</dt><dd>{risk.basis}</dd><dt>限制条件</dt><dd>{risk.limitations.join("；")}</dd></dl><button className="text-link" onClick={() => { setClaim(data.claims.find((item) => item.claim_id === risk.evidence_claim_id) ?? null); setTab("report"); }}>查看证据 →</button></div></article>)}</section>}
      {tab === "report" && <section className="report-panel report-reading"><article className="document"><p className="eyebrow">结构化研究报告</p><h2>{data.company.name} {data.company.report_period_end.slice(0,4)} 年度财报分析</h2>{data.report.sections.map((section) => <section key={section.title}><h3>{section.title}</h3>{section.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</section>)}</article><aside className="evidence-drawer"><p className="eyebrow">结论 → 证据 → PDF</p><h2>证据浏览器</h2><div className="claim-stack">{data.claims.map((item) => <button key={item.claim_id} className={claim?.claim_id===item.claim_id?"active":""} onClick={() => setClaim(item)}><span>{item.type}</span>{item.text}</button>)}</div>{claim && <div className="evidence-result"><strong>{claim.text}</strong>{claim.evidence.map((item) => <div key={`${item.page}-${item.snippet}`}><span>{item.section} · 第 {item.page} 页</span><p>{item.snippet}</p><a href={`${data.evidence_document.content_url}#page=${item.page}`} target="_blank" rel="noreferrer">打开原始页 ↗</a></div>)}</div>}</aside></section>}
      {tab === "audit" && <section className="report-panel"><div className="panel-intro"><div><p className="eyebrow">专业复核信息</p><h2>高级审计</h2></div><p>普通阅读无需处理这些工程细节。</p></div><div className="audit-grid">{Object.entries(data.audit).map(([key,value]) => <article key={key}><span>{key.replaceAll("_", " ")}</span><strong>{value}</strong></article>)}</div><div className="audit-boundary"><ShieldIcon /><div><h3>验收边界</h3><p>此状态只适用于 G001 合成黄金案例。真实中文年报仍需独立 Reviewer A/B 和正式 Goal Gate，不得据此声明真实准确率。</p></div></div></section>}
    </main>
  </div>;
}

function UploadModal({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<"email" | "code" | "upload" | "done">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [developmentCode, setDevelopmentCode] = useState<string | null>(null);
  const [company, setCompany] = useState("");
  const [securityCode, setSecurityCode] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const requestCode = async () => {
    setBusy(true); setMessage("");
    const response = await fetch("/api/v1/auth/email/request", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
    const body = await response.json() as { development_code?: string; detail?: { message?: string } };
    setBusy(false);
    if (!response.ok) { setMessage(body.detail?.message ?? "验证码发送失败，请稍后重试。"); return; }
    setDevelopmentCode(body.development_code ?? null); setStep("code");
  };
  const verifyCode = async () => {
    setBusy(true); setMessage("");
    const response = await fetch("/api/v1/auth/email/verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, code }) });
    const body = await response.json() as { detail?: { message?: string } };
    setBusy(false);
    if (!response.ok) { setMessage(body.detail?.message ?? "验证码不正确。"); return; }
    setStep("upload");
  };
  const uploadReport = async () => {
    if (!file) return;
    setBusy(true); setMessage("");
    const runResponse = await fetch("/api/v1/analysis-runs", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ company_name: company, security_code: securityCode, report_period_end: periodEnd, as_of: new Date().toISOString(), analysis_focus: ["comprehensive"] }) });
    const runBody = await runResponse.json() as { run_id?: string; detail?: { message?: string } };
    if (!runResponse.ok || !runBody.run_id) { setBusy(false); setMessage(runBody.detail?.message ?? "分析任务创建失败。"); return; }
    const form = new FormData(); form.append("file", file);
    const uploadResponse = await fetch(`/api/v1/analysis-runs/${runBody.run_id}/documents`, { method: "POST", body: form });
    const uploadBody = await uploadResponse.json() as { detail?: { message?: string } };
    if (!uploadResponse.ok) { setBusy(false); setMessage(uploadBody.detail?.message ?? "年报上传失败。"); return; }
    const executeResponse = await fetch(`/api/v1/analysis-runs/${runBody.run_id}/execute`, { method: "POST" });
    const executeBody = await executeResponse.json() as { detail?: { message?: string } };
    setBusy(false);
    if (!executeResponse.ok) { setMessage(executeBody.detail?.message ?? "自动分析启动失败。"); return; }
    setStep("done");
  };
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}><section className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-title" onMouseDown={(event) => event.stopPropagation()}><button className="modal-close" onClick={onClose} aria-label="关闭">×</button><p className="eyebrow">安全上传 · {step === "email" || step === "code" ? "邮箱验证" : "创建分析"}</p><h2 id="auth-title">{step === "done" ? "自动分析已启动" : "分析真实年报"}</h2><p>{step === "done" ? "文件已通过基础校验并进入隔离存储。系统会自动解析与定位报表，只有遇到无法唯一判断的内容才会请你确认。" : "公开示例无需登录。真实 PDF 只对你的安全会话可见。"}</p>
    {step === "email" && <><label>邮箱地址<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" autoFocus /></label><button className="button primary full" disabled={busy || !email} onClick={() => void requestCode()}>{busy ? "正在发送…" : "获取邮箱验证码"}</button></>}
    {step === "code" && <><label>6 位验证码<input inputMode="numeric" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} autoFocus /></label>{developmentCode && <div className="dev-code">开发环境验证码：<strong>{developmentCode}</strong></div>}<button className="button primary full" disabled={busy || code.length !== 6} onClick={() => void verifyCode()}>{busy ? "正在验证…" : "验证并继续"}</button></>}
    {step === "upload" && <><div className="upload-grid"><label>公司名称<input value={company} onChange={(event) => setCompany(event.target.value)} /></label><label>证券代码<input inputMode="numeric" maxLength={6} value={securityCode} onChange={(event) => setSecurityCode(event.target.value.replace(/\D/g, ""))} /></label><label>报告期<input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></label><label className="file-field">年度报告 PDF<input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label></div><button className="button primary full" disabled={busy || !company || securityCode.length !== 6 || !periodEnd || !file} onClick={() => void uploadReport()}>{busy ? "正在校验、上传并启动…" : "上传并开始分析"}</button></>}
    {step === "done" && <button className="button primary full" onClick={onClose}>完成</button>}
    {message && <div className="form-error" role="alert">{message}</div>}<small>仅支持 A 股非金融类公司的中文可检索年度报告；系统不执行交易，也不构成投资建议。</small></section></div>;
}

function Footer() { return <footer><Brand /><p>证据驱动的财报研究平台</p><span>辅助决策 · 不构成投资建议 · 不执行交易</span><a href="/legacy">内部兼容工作台</a></footer>; }

export function App() {
  const [page, setPage] = useState<"home" | "demo">(() => location.hash === "#demo" ? "demo" : "home");
  const [upload, setUpload] = useState(false);
  const showDemo = () => { location.hash = "demo"; setPage("demo"); window.scrollTo(0,0); };
  const showHome = () => { history.pushState(null, "", "/"); setPage("home"); window.scrollTo(0,0); };
  return <>{page === "demo" ? <DemoPage onBack={showHome} onUpload={() => setUpload(true)} /> : <Landing onDemo={showDemo} onUpload={() => setUpload(true)} />}{upload && <UploadModal onClose={() => setUpload(false)} />}</>;
}

const rootElement = document.getElementById("root");
if (rootElement) {
  createRoot(rootElement).render(<StrictMode><QueryClientProvider client={queryClient}><App /></QueryClientProvider></StrictMode>);
}
