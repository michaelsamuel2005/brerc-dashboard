// TanStack Query hooks — the only server-state surface. staleTime set; retry bounded and
// disabled for 4xx client errors (no retry storms against a rate-limited API).
import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { AsyncState } from "../../types";
import { ApiError } from "./client";
import { ReleaseCoherenceError } from "./releaseCoherence";
import * as api from "./endpoints";
import type { QueryParams } from "./client";
import type { SpeciesListParams } from "./endpoints";

const STALE = 60_000;

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof ReleaseCoherenceError) return false;
  if (error instanceof ApiError && error.status !== undefined && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

export const useSummary = (params?: QueryParams) =>
  useQuery({
    queryKey: ["summary", params],
    queryFn: ({ signal }) => api.getSummary(params, { signal }),
    staleTime: STALE,
    retry,
  });

export const useSpeciesList = (params?: SpeciesListParams) =>
  useQuery({
    queryKey: ["species", "list", params],
    queryFn: ({ signal }) => api.getSpecies(params, { signal }),
    placeholderData: keepPreviousData,
    staleTime: STALE,
    retry,
  });

export const useSpeciesDetail = (speciesId: string | undefined) =>
  useQuery({
    queryKey: ["species", "detail", speciesId],
    queryFn: ({ signal }) => api.getSpeciesDetail(speciesId as string, { signal }),
    enabled: Boolean(speciesId),
    staleTime: STALE,
    retry,
  });

export const useDistributionCells = (params?: QueryParams) =>
  useQuery({
    queryKey: ["cells", params],
    queryFn: ({ signal }) => api.getDistributionCells(params, { signal }),
    staleTime: STALE,
    retry,
  });

export const useRecords = (params?: QueryParams) =>
  useQuery({
    queryKey: ["records", params],
    queryFn: ({ signal }) => api.getRecords(params, { signal }),
    staleTime: STALE,
    retry,
  });

export const useProvenance = () =>
  useQuery({
    queryKey: ["provenance"],
    queryFn: ({ signal }) => api.getProvenance({ signal }),
    staleTime: STALE,
    retry,
  });

/** Map a TanStack query result into the app's discriminated-union async state. */
export function toAsyncState<T>(query: UseQueryResult<T>, isEmpty?: (data: T) => boolean): AsyncState<T> {
  if (query.isPending) return { status: "loading" };
  if (query.isError) return { status: "error", error: query.error instanceof Error ? query.error : new Error("Unknown error") };
  const data = query.data as T;
  if (isEmpty?.(data)) return { status: "empty" };
  return { status: "ready", data };
}
