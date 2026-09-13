// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";

describe("CiteFin product shell", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({}) })));
  });

  it("opens on the public value proposition without a local identity gate", () => {
    history.pushState(null, "", "/");
    render(<App />);
    expect(screen.getByRole("heading", { name: /看懂一份年报/ })).not.toBeNull();
    expect(screen.getByRole("button", { name: /查看示例报告/ })).not.toBeNull();
    expect(screen.queryByText("本地用户标识")).toBeNull();
  });

  it("renders a persisted run in the real analysis workspace", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = url.endsWith("/auth/session")
        ? { authenticated: true, user_id: "user_test" }
        : url.endsWith("/review-items")
          ? []
          : url.endsWith("/workspace")
            ? {
                run: { run_id: "run_1", company_name: "真实流程公司", security_code: "600001", report_period_end: "2025-12-31", status: "verified", current_node: "finalize", updated_at: "2026-09-13T00:00:00Z", failure_code: null },
                sources: [], statements: [], facts: Array.from({ length: 23 }, (_, index) => ({ fact_id: `fact_${index}`, concept: "revenue", label_raw: "营业收入", normalized_value: "1", period_end: "2025-12-31", page_number: 1 })),
                metrics: Array.from({ length: 15 }, (_, index) => ({ metric_code: `metric_${index}`, value: "1", unit: "ratio", status: "calculated", reason: null })),
                risks: [], reports: [{ report_id: "report_1", status: "verified", content: {} }],
                evaluations: [{ evaluation_id: "eval_1", status: "passed", blocking_reasons: [] }],
                gate_decisions: [{ gate_id: "gate_1", decision: "verified", blocking_reasons: [] }],
              }
            : [{ run_id: "run_1", company_name: "真实流程公司", security_code: "600001", report_period_end: "2025-12-31", status: "verified", current_node: "finalize", updated_at: "2026-09-13T00:00:00Z", failure_code: null }];
      return { ok: true, json: async () => json };
    }));
    history.pushState(null, "", "/#workspace=run_1");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "真实流程公司" })).not.toBeNull();
    expect(screen.getByText("报告已通过 Goal Gate")).not.toBeNull();
    expect(screen.getByText("15 / 15")).not.toBeNull();
  });
});
