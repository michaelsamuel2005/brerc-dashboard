// TanStack Query hooks — the only server-state surface. staleTime set; retry bounded and
// disabled for 4xx client errors (no retry storms against a rate-limited API).
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { AsyncState } from "../../types";
import { ApiError } from "./client";
import * as api from "./endpoints";
import type { QueryParams } from "./client";

const STALE = 60_000;

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status !== undefined && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

export const useSummary = (params?: QueryParams) =>
  useQuery({ queryKey: ["summary", params], queryFn: () => api.getSummary(params), staleTime: STALE, retry });

export const useSpeciesList = (params?: QueryParams) =>
  useQuery({ queryKey: ["species", params], queryFn: () => api.getSpecies(params), staleTime: STALE, retry });

export const useSpeciesDetail = (speciesId: string | undefined) =>
  useQuery({
    queryKey: ["species", speciesId],
    queryFn: () => api.getSpeciesDetail(speciesId as string),
    enabled: Boolean(speciesId),
    staleTime: STALE,
    retry,
  });

export const useDistributionCells = (params?: QueryParams) =>
  useQuery({ queryKey: ["cells", params], queryFn: () => api.getDistributionCells(params), staleTime: STALE, retry });

export const useRecords = (params?: QueryParams) =>
  useQuery({ queryKey: ["records", params], queryFn: () => api.getRecords(params), staleTime: STALE, retry });

export const useProvenance = () =>
  useQuery({ queryKey: ["provenance"], queryFn: () => api.getProvenance(), staleTime: STALE, retry });

/** Map a TanStack query result into the app's discriminated-union async state. */
export function toAsyncState<T>(query: UseQueryResult<T>, isEmpty?: (data: T) => boolean): AsyncState<T> {
  if (query.isPending) return { status: "loading" };
  if (query.isError) return { status: "error", error: query.error instanceof Error ? query.error : new Error("Unknown error") };
  const data = query.data as T;
  if (isEmpty?.(data)) return { status: "empty" };
  return { status: "ready", data };
}
