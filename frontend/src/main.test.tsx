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
});
