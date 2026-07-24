import { create } from "zustand";

interface UserProfile {
  displayName: string;
  avatarUrl: string | null;
}

interface UserState {
  profile: UserProfile;
  setProfile: (profile: Partial<UserProfile>) => void;
}

export const useUserStore = create<UserState>((set) => ({
  profile: {
    displayName: "用户",
    avatarUrl: null,
  },
  setProfile: (patch) => set((s) => ({ profile: { ...s.profile, ...patch } })),
}));
