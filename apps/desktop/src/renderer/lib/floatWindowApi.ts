/**
 * Preload bridge for方案 C 真 OS 浮窗（UX §十）.
 *
 * Web / 单测无 preload → helpers no-op；桌面以 `floatWindowApi` 可用性为真窗门控。
 */

import type {
  FloatWindowApi,
  FloatWindowClosedPayload,
  FloatWindowOpenInput,
} from "@shared/float-window-contract";
import { isWebRuntime } from "@/lib/capabilities";

export type {
  FloatWindowApi,
  FloatWindowClosedPayload,
  FloatWindowOpenInput,
} from "@shared/float-window-contract";

export function getFloatWindowApi(): FloatWindowApi | undefined {
  if (typeof window === "undefined") return undefined;
  return window.floatWindowApi;
}

/** 桌面 Electron 且 preload 已注入真窗 API（Web 恒 false）。 */
export function canUseOsFloatWindow(): boolean {
  if (isWebRuntime()) return false;
  const api = getFloatWindowApi();
  return Boolean(api?.open && api?.dock && api?.destroy && api?.onClosed);
}

export async function floatWindowOpen(
  input: FloatWindowOpenInput,
): Promise<boolean> {
  const api = getFloatWindowApi();
  if (!api?.open) return false;
  return Boolean(await api.open(input));
}

export async function floatWindowDock(tabId: string): Promise<boolean> {
  const api = getFloatWindowApi();
  if (!api?.dock) return false;
  await api.dock({ tabId });
  return true;
}

export async function floatWindowDestroy(tabId: string): Promise<boolean> {
  const api = getFloatWindowApi();
  if (!api?.destroy) return false;
  await api.destroy({ tabId });
  return true;
}

export function onFloatWindowClosed(
  cb: (payload: FloatWindowClosedPayload) => void,
): () => void {
  const api = getFloatWindowApi();
  if (!api?.onClosed) return () => undefined;
  return api.onClosed(cb);
}
