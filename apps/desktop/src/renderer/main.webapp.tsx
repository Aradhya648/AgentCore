// Production web client entry (P1 多端：web = 「云工作区」一等入口；前端技术与架构 §七).
//
// Installs the browser-runtime stubs for the four Electron globals and marks
// `window.__WEB__` (side-effect import, runs before ./main), then boots the real
// renderer unchanged — with REAL cookie auth (AuthGate) against `VITE_API_URL`.
//
// Contrast main.web.tsx (offline preview), which additionally imports
// ./preview/markPreview to set `__WEB_PREVIEW__` and skip auth for `#/preview`.
// Keeping the two entries separate is the whole difference between "offline render
// harness" and "real web client": same renderer, same stubs, different auth.
import "./preview/browserStubs";
import "./main";
