// index.ts — Single entry point for all data access.
// Components do: `import { api } from "@/lib/api";` and call typed methods.
//
// The adapter is selected by VITE_API_MODE at build/dev time:
//   mock (default) — MockRegOpsApi, full synthetic workflow, no backend needed
//   http           — HttpRegOpsApi against contracts/openapi.yaml
//
// Both implement RegOpsApi, so switching requires no component changes.

import type { RegOpsApi } from "./client";
import { HttpRegOpsApi } from "./httpAdapter";
import { MockRegOpsApi } from "./mockAdapter";
import { resolveApiBaseUrl, resolveApiMode } from "./mode";

export type { ListFindingsParams, RegOpsApi } from "./client";
export * from "./types";
export { isRegOpsApiError, RegOpsApiError, toRegOpsApiError } from "./errors";
export type { ApiErrorKind } from "./errors";
export { SHADOW_COPY_NOTICE, SYNTHETIC_NOTICE } from "./mockData";

export type { ApiMode } from "./mode";
export { DEFAULT_API_BASE_URL, resolveApiBaseUrl, resolveApiMode } from "./mode";

export const API_MODE = resolveApiMode(import.meta.env.VITE_API_MODE);

export const API_BASE_URL: string = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL);

function createApi(): RegOpsApi {
  if (API_MODE === "http") {
    return new HttpRegOpsApi({ baseUrl: API_BASE_URL });
  }
  return new MockRegOpsApi();
}

export const api: RegOpsApi = createApi();
