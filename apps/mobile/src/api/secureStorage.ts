import type { TokenPersistence, Tokens } from "@/api/client";
// Native (Capacitor) Secure Storage backend for the bearer token pair (前端技术与架构 §七
// 安全存储). On iOS the pair lives in the system Keychain; on Android it is AES-GCM
// encrypted with an Android Keystore key. This is the OS-level secure replacement for the
// web localStorage backend (api/client.ts) — the only place real at-rest secrecy exists
// (a browser has no Keychain). Injected from main.tsx behind Capacitor.isNativePlatform(),
// so this module (and its plugin import) only runs on a native build.
import { SecureStorage } from "@aparajita/capacitor-secure-storage";

// The plugin namespaces keys with its own prefix (`capacitor-storage_`); one entry holds
// the whole pair as JSON.
const KEY = "tokens";

function isTokens(value: unknown): value is Tokens {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Tokens).access_token === "string" &&
    typeof (value as Tokens).refresh_token === "string"
  );
}

export const capacitorSecureTokenPersistence: TokenPersistence = {
  async load() {
    try {
      // Resolves to null for a missing key; only throws on empty key / corruption / OS
      // error — all of which we treat as "no session" to honor the port's no-throw load.
      const value = await SecureStorage.get(KEY);
      return isTokens(value)
        ? {
            access_token: value.access_token,
            refresh_token: value.refresh_token,
          }
        : null;
    } catch {
      return null;
    }
  },
  async save(tokens) {
    await SecureStorage.set(KEY, {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
    });
  },
  async clear() {
    await SecureStorage.remove(KEY);
  },
};
