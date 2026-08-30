import { fileURLToPath, URL } from "node:url";
// `vitest/config` re-exports Vite's defineConfig and adds the `test` section.
import { defineConfig } from "vitest/config";
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
  build: {
    // No source maps in the deployed bundle. The published assets carry only the
    // two public VITE_ variables; they should not also ship original sources.
    sourcemap: false,
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
  test: {
    // The suite covers the API layer and pure helpers; no DOM is needed.
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
