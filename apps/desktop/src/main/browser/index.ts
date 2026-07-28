/**
 * main/browser 桶出口。
 */

export { registerBrowserIpc } from "./ipc";
export {
  startDesktopBrowserBridge,
  stopDesktopBrowserBridge,
  getDesktopBrowserBridgeInfo,
  getDesktopBrowserBridgeCredentials,
  rotateDesktopBrowserBridgeCredentials,
} from "./bridge";
export { closeAllLocalBrowserPages } from "./host";
