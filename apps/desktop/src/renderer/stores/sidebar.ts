import { createZustandUiStorage } from "@/lib/uiStorage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

const uiPersistStorage = createJSONStorage(() => createZustandUiStorage());

interface SidebarState {
  collapsed: boolean;
  /** Per-section expand state, keyed by section id. Workspace groups key on their
   * `folderId`; an absent key means "no explicit user choice yet" (the view then
   * applies its own default — see `WorkspaceGroups`). */
  expandedSections: Record<string, boolean>;

  toggleCollapsed: () => void;
  setCollapsed: (collapsed: boolean) => void;
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
      expandedSections: {},

      toggleCollapsed: () => set((s) => ({ collapsed: !s.collapsed })),
      setCollapsed: (collapsed) => set({ collapsed }),
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
      // Persist only view prefs (rail collapse + per-workspace expand state) so
      // expanded projects stay open across restarts; methods aren't serialized.
      partialize: (s) => ({
        collapsed: s.collapsed,
        expandedSections: s.expandedSections,
      }),
    },
  ),
);
