import { App } from "@/App";
import { setTokenPersistence } from "@/api/client";
import { capacitorSecureTokenPersistence } from "@/api/secureStorage";
import { Capacitor } from "@capacitor/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "@/styles.css";

// On a native build, persist the bearer tokens in the OS Keychain/Keystore instead of the
// web localStorage default. Must run before the first hydrateTokens() (App's bootstrap),
// so the restored session reads from secure storage. Web keeps the localStorage default.
if (Capacitor.isNativePlatform()) {
  setTokenPersistence(capacitorSecureTokenPersistence);
}

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
