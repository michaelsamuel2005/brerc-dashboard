// The ONE network entry point. Nothing else in the app calls fetch. Every response is
// Zod-parsed before it returns; non-200, timeout and validation failures surface as a
// typed ApiError, never a silent crash.
import { z } from "zod";
import { config } from "../../config";

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

// Abortable request for a real timeout. Some runtimes (notably jsdom under Node in
// tests) ship an AbortSignal that Node's fetch rejects — in that case we fall back to
// a plain, non-abortable request so behaviour is correct in every environment.
async function fetchWithTimeout(url: URL, timeoutMs: number): Promise<Response> {
  const headers = { Accept: "application/json" };
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { signal: controller.signal, headers });
    } finally {
      clearTimeout(timer);
    }
  } catch (err) {
    if (err instanceof Error && /abortsignal/i.test(err.message)) {
      return await fetch(url, { headers });
    }
    throw err;
  }
}

export async function getJson<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  params?: QueryParams,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<z.output<S>> {
  const base = config.apiBaseUrl.replace(/\/$/, "");
  const url = new URL(base + path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }

  try {
    const res = await fetchWithTimeout(url, timeoutMs);
    if (!res.ok) throw new ApiError(`Request failed (${res.status})`, res.status);
    const body: unknown = await res.json();
    return schema.parse(body) as z.output<S>;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof z.ZodError) {
      throw new ApiError(`Response failed validation: ${err.issues.map((i) => i.path.join(".") || "root").join(", ")}`);
    }
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError("Request timed out");
    throw new ApiError(err instanceof Error ? err.message : "Network error");
  }
}
