/** Renderer-side host OS detection (matches main process `process.platform === "darwin"`). */
export const isMac =
  typeof navigator !== "undefined" && /mac/i.test(navigator.userAgent);

/** Left inset for frameless + hiddenInset traffic lights (`main/index.ts` trafficLightPosition). */
export const macTitleBarInsetClass = "pl-[72px]";
