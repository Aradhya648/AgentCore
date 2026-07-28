/**
 * 脱离主进程 Local 浏览器 Attachment（保活）。
 * 关坞 / 关浏览器 tab / 切对话等在改 React 状态前调用。
 */
export function detachLocalBrowserHost(): Promise<void> {
  const api = typeof window !== "undefined" ? window.browserApi : undefined;
  if (!api?.hide) return Promise.resolve();
  return Promise.resolve(api.hide()).then(() => undefined);
}
