/** True when running under `#/preview` offline conformance replay (`main.web.tsx`). */
export function isWebPreview(): boolean {
  return typeof window !== "undefined" && window.__WEB_PREVIEW__ === true;
}
