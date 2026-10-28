import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Dev server proxies `/api` to the FastAPI backend so the browser only ever
 * talks to one origin - the same relative URLs work unchanged behind the nginx
 * build in production. Test configuration lives in `vitest.config.ts`.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
