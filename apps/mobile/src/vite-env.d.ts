/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  /** Dev-only auto-login credentials; see apps/mobile/.env.example. DEV builds only. */
  readonly VITE_DEV_USERNAME?: string;
  readonly VITE_DEV_PASSWORD?: string;
  /**
   * Native FCM push. Must be `"true"` only when `android/app/google-services.json` is
   * present — otherwise `PushNotifications.register()` native-crashes Android.
   */
  readonly VITE_PUSH_ENABLED?: string;
}
