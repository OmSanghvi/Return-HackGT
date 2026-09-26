/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the real backend, or unset for mock mode. See src/config.ts. */
  readonly VITE_SKETCHSCAPE_API_URL?: string;
  /** Comma-separated hardcoded account ids; defaults to demo-alice,demo-bob. */
  readonly VITE_SKETCHSCAPE_ACCOUNTS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
