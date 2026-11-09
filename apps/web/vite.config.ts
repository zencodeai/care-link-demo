import { defineConfig } from "vite";

export default defineConfig({
  optimizeDeps: { include: ["@care-link/contracts"] },
  build: {
    commonjsOptions: {
      include: [/node_modules/, /validators\.generated\.cjs$/],
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/dev": "http://127.0.0.1:8011" },
  },
});
