// index.ts — Single entry point for all data access.
// Components do: `import { api } from "@/lib/api";`  and call typed methods.
//
// To switch from mock to the real backend, implement HttpRegOpsApi (a fetch client
// against contracts/openapi.yaml) and change the one line in `createApi()`. No
// component changes required.

import type { RegOpsApi } from "./client";
import { MockRegOpsApi } from "./mockAdapter";

export type { RegOpsApi, ListFindingsParams } from "./client";
export * from "./types";
export { SYNTHETIC_NOTICE } from "./mockData";

// Flip this (or wire to import.meta.env.VITE_USE_REAL_API) once the backend is live.
const USE_REAL_API = false;

function createApi(): RegOpsApi {
  if (USE_REAL_API) {
    // return new HttpRegOpsApi(import.meta.env.VITE_API_BASE_URL ?? "/api/v1");
    throw new Error("Real API client not implemented yet — set USE_REAL_API=false.");
  }
  return new MockRegOpsApi();
}

export const api: RegOpsApi = createApi();
