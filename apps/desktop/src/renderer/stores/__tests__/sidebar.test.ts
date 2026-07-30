import { beforeEach, describe, expect, it } from "vitest";
import {
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  useSidebarStore,
} from "../sidebar";

const store = () => useSidebarStore.getState();

beforeEach(() => {
  useSidebarStore.setState({
    collapsed: false,
    width: SIDEBAR_DEFAULT_WIDTH,
    expandedSections: { "folder-a": true },
  });
});

describe("sidebar store", () => {
  describe("toggleCollapsed", () => {
    it("toggles collapsed state", () => {
      expect(store().collapsed).toBe(false);

      store().toggleCollapsed();
      expect(store().collapsed).toBe(true);

      store().toggleCollapsed();
      expect(store().collapsed).toBe(false);
    });
  });

  describe("setCollapsed", () => {
    it("sets collapsed to specific value", () => {
      store().setCollapsed(true);
      expect(store().collapsed).toBe(true);

      store().setCollapsed(false);
      expect(store().collapsed).toBe(false);
    });
  });

  describe("setWidth / resetWidth", () => {
    it("sets width within bounds", () => {
      store().setWidth(320);
      expect(store().width).toBe(320);
    });

    it("clamps below min (only widen — floor is default)", () => {
      store().setWidth(SIDEBAR_MIN_WIDTH - 40);
      expect(store().width).toBe(SIDEBAR_MIN_WIDTH);
    });

    it("clamps above max", () => {
      store().setWidth(SIDEBAR_MAX_WIDTH + 80);
      expect(store().width).toBe(SIDEBAR_MAX_WIDTH);
    });

    it("rounds to nearest px", () => {
      store().setWidth(300.6);
      expect(store().width).toBe(301);
    });

    it("resetWidth restores default", () => {
      store().setWidth(360);
      store().resetWidth();
      expect(store().width).toBe(SIDEBAR_DEFAULT_WIDTH);
    });
  });

  describe("toggleSection", () => {
    it("toggles a section open/closed", () => {
      expect(store().expandedSections["folder-a"]).toBe(true);

      store().toggleSection("folder-a");
      expect(store().expandedSections["folder-a"]).toBe(false);

      store().toggleSection("folder-a");
      expect(store().expandedSections["folder-a"]).toBe(true);
    });

    it("defaults undefined sections to toggled on", () => {
      store().toggleSection("new-folder");
      expect(store().expandedSections["new-folder"]).toBe(true);
    });
  });

  describe("setSection", () => {
    it("sets a section to an explicit value regardless of prior state", () => {
      store().setSection("ws-1", false);
      expect(store().expandedSections["ws-1"]).toBe(false);

      store().setSection("ws-1", true);
      expect(store().expandedSections["ws-1"]).toBe(true);
    });

    it("leaves other sections untouched", () => {
      store().setSection("ws-1", true);
      expect(store().expandedSections["folder-a"]).toBe(true);
    });
  });
});
