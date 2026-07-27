import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initScrollReveal } from "./lib/scrollReveal";
import { applyTheme } from "./lib/theme";
import { startOutboxReconcile } from "./services/outboxReconcile";
import { installSidecarEventPump } from "./services/sidecarEventPump";
import { installSidecarStatusListener } from "./services/sidecarStatus";
import { useUIStore } from "./stores/ui";
import "./styles/globals.css";

initScrollReveal();
// Consume the sidecar lifecycle/diagnostic channel so a local-engine spawn/exit
// failure surfaces its real reason on a failed turn, not a generic "network"
// banner (no-op outside the desktop shell). See services/sidecarStatus.
installSidecarStatusListener();
// Single App-lifetime `sidecar:event` subscription; turns claim sinks (叠字根因：
// 多 onEvent listener). See services/sidecarEventPump.
installSidecarEventPump();
// Main-process outbox sync acks + exit flush (as-built: 前端技术 §7.2).
startOutboxReconcile();
// Apply the persisted theme before the first paint to avoid a light→dark flash
// (the store reads the saved choice from localStorage on creation).
applyTheme(useUIStore.getState().theme);

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Root element #root not found");

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
