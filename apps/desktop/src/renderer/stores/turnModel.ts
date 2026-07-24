import { create } from "zustand";

/**
 * 每个会话「最近一次本地(sidecar)回合实际使用的聊天模型」——喂给输入框的
 * {@link import("@/components/chat/message-input/ModelPicker").ModelPicker}
 * 使其如实反映**这一回合真的跑在哪个模型上**，而非仅账号配置（账号默认聊天服务商的
 * `default_model`，见 `GET /v1/users/me/llm-providers`）。
 *
 * 为什么需要它：云回合恒用账号模型（徽章读账号配置就已正确），唯一会分叉的是本机 sidecar 的
 * dev 回退——取不到云推理令牌时回合会静默跑在本机 `.env` 平台模型（如 deepseek-v4-flash）而非账号模型
 * （如 deepseek-…）。sidecar 回合结果里带回它真正解析出的模型（`SidecarTurnResult.model` =
 * 引擎内 `resolve_turn_model`），本 store 按会话记下，徽章据此显示真实模型。
 *
 * 仅本地回合写入（`streamConversationViaSidecar` / `resumeConversationViaSidecar` 收到结果后）。
 * 没有记录的会话（全新会话、纯云会话）→ 徽章回退到既有的账号配置文案。刻意与庞大的会话 store
 * 分开：这是一条独立、只读展示用的旁路信号，隔离可减少并行改动的冲突面。
 */
interface TurnModelState {
  /** conversationId → 该会话最近一次本地回合实际使用的模型名。 */
  byConversation: Record<string, string>;
  /** 记录某会话本回合真正跑的模型（本地回合结果回来时调用）。空值忽略。 */
  setLastModel: (
    conversationId: string,
    model: string | null | undefined,
  ) => void;
  /** 删除对话时丢掉该会话的模型旁路信号，避免 byConversation 泄漏。 */
  clearConversation: (conversationId: string) => void;
}

export const useTurnModelStore = create<TurnModelState>((set) => ({
  byConversation: {},
  setLastModel: (conversationId, model) => {
    const trimmed = model?.trim();
    if (!conversationId || !trimmed) return;
    set((state) =>
      state.byConversation[conversationId] === trimmed
        ? state
        : {
            byConversation: {
              ...state.byConversation,
              [conversationId]: trimmed,
            },
          },
    );
  },
  clearConversation: (conversationId) =>
    set((state) => {
      if (!(conversationId in state.byConversation)) return state;
      const { [conversationId]: _, ...rest } = state.byConversation;
      return { byConversation: rest };
    }),
}));
