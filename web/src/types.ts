// The data contracts shared by the UI and the API. These mirror the backend's
// response shapes (api/app/models.py). As the front-end owner you develop against
// these; a backend teammate makes the real API match them.

export interface SpeciesMatch {
  scientific_name: string;
  common_name: string | null;
  taxon_group: string | null;
}

export interface FilterOptions {
  taxon_groups: string[];
  datasets: string[];
  year_min: number | null;
  year_max: number | null;
}

export interface SummaryStats {
  total_records: number;
  total_species: number;
  total_datasets: number;
  year_min: number | null;
  year_max: number | null;
}

/** One generalised, counted grid cell — the accessible table equivalent of a map feature. */
export interface OccurrenceCell {
  scientific_name: string;
  common_name: string | null;
  taxon_group: string | null;
  public_gridref: string | null;
  resolution_m: number;
  is_sensitive: boolean;
  occurrence_count: number;
  first_year: number | null;
  last_year: number | null;
  lon: number;
  lat: number;
}

export interface OccurrenceCells {
  cells: OccurrenceCell[];
  returned: number;
  capped: boolean;
}

export interface SpeciesInfo {
  scientific_name: string;
  common_name: string | null;
  has_image: boolean;
  image_url: string | null;
  image_licence: string | null;
  image_attribution: string | null;
  image_source: string | null;
  description: string | null;
  description_source: string | null;
  description_licence: string | null;
  description_url: string | null;
  fetched_at: string | null;
}

/** The filters that drive both the map and the table. */
export interface Filters {
  scientificName: string | null;
  taxonGroup: string | null;
  yearFrom: number | null;
  yearTo: number | null;
}

export const EMPTY_FILTERS: Filters = {
  scientificName: null,
  taxonGroup: null,
  yearFrom: null,
  yearTo: null,
};

/** The data source the UI talks to (satisfied by both the mock and the real client). */
export interface DashboardApi {
  summary(): Promise<SummaryStats>;
  filters(): Promise<FilterOptions>;
  searchSpecies(q: string): Promise<SpeciesMatch[]>;
  cells(filters: Filters): Promise<OccurrenceCells>;
  speciesInfo(scientificName: string, commonName?: string | null): Promise<SpeciesInfo>;
}
