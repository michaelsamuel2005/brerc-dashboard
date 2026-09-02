// The ONE network entry point. Nothing else in the app calls fetch. Every response is
// Zod-parsed before it returns; non-200, timeout and validation failures surface as a
// typed ApiError, never a silent crash.
import { z } from "zod";
import { config } from "../../config";
import { enforceReleaseCoherence, ReleaseCoherenceError } from "./releaseCoherence";

export class ApiError extends Error {
  readonly status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const DEFAULT_TIMEOUT_MS = 10_000;

export type QueryParams = Record<string, string | number | undefined>;

export interface GetJsonOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
  /** Only the recovery coordinator may bypass the currently pinned identity. */
  releaseAuthority?: boolean;
}

// Abortable request for a real timeout. Some runtimes (notably jsdom under Node in
// tests) ship an AbortSignal that Node's fetch rejects — in that case we fall back to
// a plain, non-abortable request so behaviour is correct in every environment.
async function fetchWithTimeout(
  url: URL,
  timeoutMs: number,
  externalSignal?: AbortSignal,
): Promise<Response> {
  const headers = { Accept: "application/json" };
  try {
    const controller = new AbortController();
    const cancelFromCaller = () => controller.abort();
    if (externalSignal?.aborted) controller.abort();
    else externalSignal?.addEventListener("abort", cancelFromCaller, { once: true });
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { signal: controller.signal, headers });
    } finally {
      clearTimeout(timer);
      externalSignal?.removeEventListener("abort", cancelFromCaller);
    }
  } catch (err) {
    if (
      !externalSignal?.aborted &&
      err instanceof Error &&
      /abortsignal/i.test(err.message)
    ) {
      return await fetch(url, { headers });
    }
    throw err;
  }
}

export async function getJson<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  params?: QueryParams,
  options: GetJsonOptions = {},
): Promise<z.output<S>> {
  if (options.releaseAuthority === true && path !== "/meta/provenance") {
    throw new ApiError("Only provenance may establish the active release identity");
  }
  const base = config.apiBaseUrl.replace(/\/$/, "");
  const url = new URL(base + path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }

  try {
    const res = await fetchWithTimeout(
      url,
      options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
      options.signal,
    );
    if (!res.ok) throw new ApiError(`Request failed (${res.status})`, res.status);
    const body: unknown = await res.json();
    const parsed = schema.parse(body) as z.output<S>;
    return enforceReleaseCoherence(parsed, {
      authority: options.releaseAuthority === true,
    });
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof ReleaseCoherenceError) throw err;
    if (err instanceof z.ZodError) {
      throw new ApiError(`Response failed validation: ${err.issues.map((i) => i.path.join(".") || "root").join(", ")}`);
    }
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError("Request timed out");
    throw new ApiError(err instanceof Error ? err.message : "Network error");
  }
}
