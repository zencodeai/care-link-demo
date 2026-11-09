/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_SURFACE?: "main" | "help";
  readonly VITE_HELP_ORIGIN?: string;
  readonly VITE_OIDC_ORIGIN?: string;
  readonly VITE_STATIC_ORIGIN?: string;
}
