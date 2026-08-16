import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend never hardcodes a backend host. In `http` mode the API layer calls
// the relative base path (default `/api/v1`); this proxy points that at a locally
// running RegOps API during development.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env["REGOPS_API_PROXY"] ?? "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
