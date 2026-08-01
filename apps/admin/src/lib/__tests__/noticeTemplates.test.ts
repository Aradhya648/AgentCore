import { describe, expect, it } from "vitest";
import {
  NOTICE_TEMPLATES,
  buildFromSlots,
  emptySlotValues,
  surfacePublishHint,
  templateToFormSeed,
} from "../noticeTemplates";

describe("noticeTemplates", () => {
  it("exposes eight operational templates with required fields", () => {
    expect(NOTICE_TEMPLATES).toHaveLength(8);
    for (const t of NOTICE_TEMPLATES) {
      expect(t.id).toBeTruthy();
      expect(t.title.trim().length).toBeGreaterThan(0);
      expect(t.body.trim().length).toBeGreaterThan(0);
      expect(t.slots.length).toBeGreaterThan(0);
      expect(["critical", "high", "normal"]).toContain(t.severity);
      expect(["banner", "inbox", "both", "modal"]).toContain(t.surface);
      expect(["once", "never"]).toContain(t.dismiss_policy);
    }
  });

  it("never pairs modal with dismiss=never", () => {
    for (const t of NOTICE_TEMPLATES) {
      if (t.surface === "modal") {
        expect(t.dismiss_policy).toBe("once");
      }
    }
  });

  it("templateToFormSeed copies recommended fields and clears CTA/window", () => {
    const seed = templateToFormSeed(NOTICE_TEMPLATES[0]!);
    expect(seed.title).toBe(NOTICE_TEMPLATES[0]!.title);
    expect(seed.severity).toBe(NOTICE_TEMPLATES[0]!.severity);
    expect(seed.cta_label).toBe("");
    expect(seed.end_at).toBe("");
  });

  it("buildFromSlots fills hotfix copy from slot values", () => {
    const hotfix = NOTICE_TEMPLATES.find((t) => t.id === "hotfix")!;
    const built = buildFromSlots(hotfix, {
      time: "14:30",
      summary: "修复消息发送超时",
    });
    expect(built.title).toBe("系统更新 · 约 14:30");
    expect(built.body).toContain("今天 14:30");
    expect(built.body).toContain("修复消息发送超时");
  });

  it("buildFromSlots keeps skeleton when slots empty", () => {
    const hotfix = NOTICE_TEMPLATES.find((t) => t.id === "hotfix")!;
    const built = buildFromSlots(hotfix, emptySlotValues(hotfix));
    expect(built.title).toContain("HH:MM");
    expect(built.body).toContain("一句话变更摘要");
  });

  it("buildFromSlots formats release highlights as numbered lines", () => {
    const release = NOTICE_TEMPLATES.find((t) => t.id === "release")!;
    const built = buildFromSlots(release, {
      version: "0.4.2",
      time: "10:00",
      highlights: "消息编辑\n撤回优化\n多余行应被截断\n不会出现",
    });
    expect(built.title).toBe("版本更新 · 0.4.2 · 约 10:00");
    expect(built.body).toContain("1. 消息编辑");
    expect(built.body).toContain("2. 撤回优化");
    expect(built.body).toContain("3. 多余行应被截断");
    expect(built.body).not.toContain("不会出现");
  });

  it("surfacePublishHint warns on invalid modal+never", () => {
    expect(surfacePublishHint("modal", "never")).toMatch(/仅支持/);
    expect(surfacePublishHint("both", "once")).toMatch(/横幅/);
    expect(surfacePublishHint("both", "once")).toMatch(/官方/);
  });
});
