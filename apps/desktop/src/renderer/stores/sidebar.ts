import { createZustandUiStorage } from "@/lib/uiStorage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

const uiPersistStorage = createJSONStorage(() => createZustandUiStorage());

/** Expanded-rail width bounds (px). Floor equals default — only widen. */
export const SIDEBAR_MIN_WIDTH = 240;
export const SIDEBAR_DEFAULT_WIDTH = 240;
export const SIDEBAR_MAX_WIDTH = 400;
/** Collapsed icon rail — fixed, not part of the drag range. */
export const SIDEBAR_COLLAPSED_WIDTH = 56;

export function clampSidebarWidth(w: number): number {
  return Math.max(
    SIDEBAR_MIN_WIDTH,
    Math.min(SIDEBAR_MAX_WIDTH, Math.round(w)),
  );
}

interface SidebarState {
  collapsed: boolean;
  /** Expanded-rail width in px, clamped to [240, 400] (persisted). */
  width: number;
  /** True while the user is dragging the resize handle (session-only; not persisted). */
  resizing: boolean;
  /** Per-section expand state, keyed by section id. Workspace groups key on their
   * `folderId`; an absent key means "no explicit user choice yet" (the view then
   * applies its own default — see `WorkspaceGroups`). */
  expandedSections: Record<string, boolean>;

  toggleCollapsed: () => void;
  setCollapsed: (collapsed: boolean) => void;
  setWidth: (width: number) => void;
  setResizing: (resizing: boolean) => void;
  /** Double-click resize handle → restore default width. */
  resetWidth: () => void;
  toggleSection: (sectionId: string) => void;
  /** Explicitly set a section's expand state. Preferred over `toggleSection` where
   * the displayed default differs from the stored value (e.g. an auto-expanded
   * active group) — clicking must flip what the user *sees*, not the absent key. */
  setSection: (sectionId: string, expanded: boolean) => void;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      collapsed: false,
      width: SIDEBAR_DEFAULT_WIDTH,
      resizing: false,
      expandedSections: {},

      toggleCollapsed: () => set((s) => ({ collapsed: !s.collapsed })),
      setCollapsed: (collapsed) => set({ collapsed }),
      setWidth: (width) => set({ width: clampSidebarWidth(width) }),
      setResizing: (resizing) => set({ resizing }),
      resetWidth: () => set({ width: SIDEBAR_DEFAULT_WIDTH }),
      toggleSection: (sectionId) =>
        set((s) => ({
          expandedSections: {
            ...s.expandedSections,
            [sectionId]: !s.expandedSections[sectionId],
          },
        })),
      setSection: (sectionId, expanded) =>
        set((s) => ({
          expandedSections: { ...s.expandedSections, [sectionId]: expanded },
        })),
    }),
    {
      name: "sidebar",
      storage: uiPersistStorage,
      // Persist only view prefs (rail collapse + width + per-workspace expand) so
      // layout survives restarts; methods / ephemeral drag flag aren't serialized.
      partialize: (s) => ({
        collapsed: s.collapsed,
        width: s.width,
        expandedSections: s.expandedSections,
      }),
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        state.width = clampSidebarWidth(
          typeof state.width === "number" && Number.isFinite(state.width)
            ? state.width
            : SIDEBAR_DEFAULT_WIDTH,
        );
      },
    },
  ),
);
