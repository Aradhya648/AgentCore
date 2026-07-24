// Offline-preview marker (side-effect import). Sets `window.__WEB_PREVIEW__` so
// AuthGate skips its auth bootstrap and renders `#/preview` fully offline (no
// backend). Imported ONLY by main.web.tsx (the screenshot / preview harness) — NOT
// by the production web client (main.webapp.tsx), which keeps real cookie auth.
// Split out from browserStubs so the shared native stubs (also used by the web
// client) don't drag the auth-skip behavior along with them.
if (typeof window !== "undefined") {
  window.__WEB_PREVIEW__ = true;
}
