/**
 * 桌面默认本地**容器根**（双模式工作区 §八.7 / 工作区对称化 D1a）。
 *
 * 桌面裸聊默认走云 scratch（`local_container_root_id=null`）。本模块只在用户**显式**
 * 选「本机草稿」或创建本地项目时，解析/授权容器根（主进程 `fsApi.ensureDefaultRoot`
 * 建 + 授权 `~/Documents/AgentCore`），供建会话写入 `local_container_root_id`。
 * 不建任何 Folder，也不预建 per-对话子目录（懒建 `conversations/<id>/`）。
 *
 * web / 手机无 `window.fsApi`，整模块 no-op（恒 null）。
 */

import { hasLocalFiles } from "@/lib/capabilities";

// 本次会话内已解析出的默认容器根 id（解析一次后缓存复用）。
let cachedRootId: string | null = null;
// 进行中的解析（防 StrictMode 双触发 / 并发点击重复授权）。
let inflight: Promise<string | null> | null = null;

/** 桌面 FS 桥是否可用（web：否 → 整条本地路径 no-op）。 */
function isDesktop(): boolean {
  return hasLocalFiles();
}

/**
 * 确保桌面默认本地容器根（`~/Documents/AgentCore`）存在并授权，返回其 root id
 * （非桌面 / 失败 → null）。
 *
 * 幂等且并发安全：解析一次后缓存。**不创建任何 Folder / 对话子目录**——裸聊 scratch
 * 路径由 `conversations/<conversation_id>/` 决定（见 bareScratchPath），首次需要时懒建。
 * 失败只记录、返回 null。仅在显式本机草稿 / 本地项目创建路径调用。
 */
export async function ensureDefaultContainerRoot(): Promise<string | null> {
  if (!isDesktop()) return null;
  if (cachedRootId) return cachedRootId;
  if (inflight) return inflight;

  inflight = (async () => {
    try {
      const root = await window.fsApi.ensureDefaultRoot();
      cachedRootId = root.id;
      return root.id;
    } catch (e) {
      console.error("[workspace] 默认本地容器根初始化失败", e);
      return null;
    } finally {
      inflight = null;
    }
  })();

  return inflight;
}
