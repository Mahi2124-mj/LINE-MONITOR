/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional absolute backend origin, e.g. "http://192.168.1.10:6010". Empty = same origin / Vite proxy. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
