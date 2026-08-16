/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" (default) or "http" — selects the adapter in src/lib/api/index.ts. */
  readonly VITE_API_MODE?: string;
  /** Base path for the real HTTP client, e.g. "/api/v1". */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
