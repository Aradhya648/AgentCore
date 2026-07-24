/**
 * Minimal preload for the cookie verifier renderer. Exposes only the three IPC
 * round-trips the verify page needs (config in, cookie snapshot, result out) over
 * contextBridge — same isolation posture as the real app's preload.
 */
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("verify", {
  config: () => ipcRenderer.invoke("verify:config"),
  cookies: () => ipcRenderer.invoke("verify:cookies"),
  report: (result) => ipcRenderer.invoke("verify:report", result),
});
