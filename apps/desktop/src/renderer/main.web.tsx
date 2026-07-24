// Plain-browser entry for the screenshot harness (scripts/shoot.mjs) and the offline
// `#/preview` (`pnpm dev:web`). Installs the Electron-global stubs + `window.__WEB__`
// (browserStubs), then marks `__WEB_PREVIEW__` (markPreview) so AuthGate skips auth and
// the app renders fully offline, then boots the real renderer unchanged. The production
// web client (main.webapp.tsx) shares the stubs but omits markPreview to keep real auth.
import "./preview/browserStubs";
import "./preview/markPreview";
import "./main";
