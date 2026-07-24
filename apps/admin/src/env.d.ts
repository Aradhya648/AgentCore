/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API origin; defaults to http://localhost:8000 (see services/api.ts). */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
