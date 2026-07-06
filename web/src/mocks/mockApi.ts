import type { DashboardApi, Filters, SpeciesInfo } from '../types';
import { CELLS, FILTERS, SPECIES, SPECIES_INFO, SUMMARY } from './fixtures';

const delay = (ms = 200) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function placeholder(name: string): SpeciesInfo {
  return {
    scientific_name: name, common_name: null, has_image: false, image_url: null,
    image_licence: null, image_attribution: null, image_source: null, description: null,
    description_source: null, description_licence: null, description_url: null, fetched_at: null,
  };
}

/** A stand-in for the real API, returning the fixtures. Used until the backend exists. */
export const mockApi: DashboardApi = {
  async summary() {
    await delay();
    return SUMMARY;
  },
  async filters() {
    await delay();
    return FILTERS;
  },
  async searchSpecies(q: string) {
    await delay();
    const s = q.trim().toLowerCase();
    return SPECIES.filter(
      (m) =>
        m.scientific_name.toLowerCase().includes(s) ||
        (m.common_name ?? '').toLowerCase().includes(s),
    );
  },
  async cells(filters: Filters) {
    await delay();
    let cells = CELLS;
    if (filters.scientificName) cells = cells.filter((c) => c.scientific_name === filters.scientificName);
    if (filters.taxonGroup) cells = cells.filter((c) => c.taxon_group === filters.taxonGroup);
    const from = filters.yearFrom;
    const to = filters.yearTo;
    if (from !== null) cells = cells.filter((c) => (c.last_year ?? 0) >= from);
    if (to !== null) cells = cells.filter((c) => (c.first_year ?? 9999) <= to);
    return { cells, returned: cells.length, capped: false };
  },
  async speciesInfo(scientificName: string) {
    await delay();
    return SPECIES_INFO[scientificName] ?? placeholder(scientificName);
  },
};
