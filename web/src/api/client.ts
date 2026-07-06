// The data layer your components import. By default it returns MOCK data so you
// can build the whole UI with no backend running. When a teammate's API is ready,
// set VITE_USE_MOCKS=false to hit the real endpoints — nothing else changes.
import { API_BASE, TILE_SOURCE, TILES_BASE } from '../config';
import { mockApi } from '../mocks/mockApi';
import type {
  DashboardApi,
  FilterOptions,
  Filters,
  OccurrenceCells,
  SpeciesInfo,
  SpeciesMatch,
  SummaryStats,
} from '../types';

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== 'false';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function getJson<T>(
  path: string,
  params?: Record<string, string | number | null>,
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }
  }
  const response = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new ApiError(response.status, `API request failed (${response.status}) for ${path}`);
  return (await response.json()) as T;
}

export function filtersToParams(filters: Filters): Record<string, string | number | null> {
  return {
    scientific_name: filters.scientificName,
    taxon_group: filters.taxonGroup,
    year_from: filters.yearFrom,
    year_to: filters.yearTo,
  };
}

const realApi: DashboardApi = {
  summary: () => getJson<SummaryStats>('/occurrences/summary'),
  filters: () => getJson<FilterOptions>('/species/filters'),
  searchSpecies: (q) => getJson<SpeciesMatch[]>('/species/search', { q, limit: 20 }),
  cells: (filters) => getJson<OccurrenceCells>('/occurrences/cells', { ...filtersToParams(filters), limit: 2000 }),
  speciesInfo: (scientificName, commonName) =>
    getJson<SpeciesInfo>('/species-info', { scientific_name: scientificName, common_name: commonName ?? null }),
};

/** Mock by default; the real API when VITE_USE_MOCKS=false. */
export const api: DashboardApi = USE_MOCKS ? mockApi : realApi;

/** Martin tile URL for the current filters (used once the tiles/backend exist). */
export function tileUrlTemplate(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.scientificName) params.set('scientific_name', filters.scientificName);
  if (filters.taxonGroup) params.set('taxon_group', filters.taxonGroup);
  if (filters.yearFrom !== null) params.set('year_from', String(filters.yearFrom));
  if (filters.yearTo !== null) params.set('year_to', String(filters.yearTo));
  const query = params.toString();
  return `${TILES_BASE}/${TILE_SOURCE}/{z}/{x}/{y}${query ? `?${query}` : ''}`;
}
