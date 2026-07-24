import { create } from "zustand";

/**
 * The「分享对话」dialog target. Sharing has two entry points (the sidebar context
 * menu and the command palette), so the dialog is mounted once at the app shell and
 * driven by this store rather than each entry owning a copy. `conversationId === null`
 * means closed; setting it opens the dialog for that conversation.
 */
interface ShareState {
  conversationId: string | null;
  open: (conversationId: string) => void;
  close: () => void;
}

export const useShareStore = create<ShareState>((set) => ({
  conversationId: null,
  open: (conversationId) => set({ conversationId }),
  close: () => set({ conversationId: null }),
}));
