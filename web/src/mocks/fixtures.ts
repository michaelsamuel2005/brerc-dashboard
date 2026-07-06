// Realistic FAKE data so the front end can be built with no backend running.
// Not real BRERC data. Delete or ignore once the real API is wired in.
import type {
  FilterOptions,
  OccurrenceCell,
  SpeciesInfo,
  SpeciesMatch,
  SummaryStats,
} from '../types';

export const SPECIES: SpeciesMatch[] = [
  { scientific_name: 'Lutra lutra', common_name: 'Otter', taxon_group: 'mammal' },
  { scientific_name: 'Erithacus rubecula', common_name: 'Robin', taxon_group: 'bird' },
  { scientific_name: 'Parus major', common_name: 'Great Tit', taxon_group: 'bird' },
  { scientific_name: 'Vulpes vulpes', common_name: 'Red Fox', taxon_group: 'mammal' },
  { scientific_name: 'Rana temporaria', common_name: 'Common Frog', taxon_group: 'amphibian' },
];

export const FILTERS: FilterOptions = {
  taxon_groups: ['amphibian', 'bird', 'mammal'],
  datasets: ['BRERC casual records', 'Bristol Bird Club'],
  year_min: 1990,
  year_max: 2025,
};

export const SUMMARY: SummaryStats = {
  total_records: 48213,
  total_species: 5,
  total_datasets: 2,
  year_min: 1990,
  year_max: 2025,
};

// A handful of cells around the West of England (lon/lat = cell centres).
export const CELLS: OccurrenceCell[] = [
  { scientific_name: 'Erithacus rubecula', common_name: 'Robin', taxon_group: 'bird', public_gridref: 'ST 59 73', resolution_m: 1000, is_sensitive: false, occurrence_count: 240, first_year: 1998, last_year: 2024, lon: -2.59, lat: 51.454 },
  { scientific_name: 'Parus major', common_name: 'Great Tit', taxon_group: 'bird', public_gridref: 'ST 58 72', resolution_m: 1000, is_sensitive: false, occurrence_count: 132, first_year: 2001, last_year: 2025, lon: -2.61, lat: 51.446 },
  { scientific_name: 'Vulpes vulpes', common_name: 'Red Fox', taxon_group: 'mammal', public_gridref: 'ST 57 71', resolution_m: 1000, is_sensitive: false, occurrence_count: 54, first_year: 2005, last_year: 2023, lon: -2.63, lat: 51.438 },
  { scientific_name: 'Lutra lutra', common_name: 'Otter', taxon_group: 'mammal', public_gridref: 'ST 5 7', resolution_m: 10000, is_sensitive: true, occurrence_count: 12, first_year: 2010, last_year: 2022, lon: -2.6, lat: 51.42 },
  { scientific_name: 'Rana temporaria', common_name: 'Common Frog', taxon_group: 'amphibian', public_gridref: 'ST 60 74', resolution_m: 1000, is_sensitive: false, occurrence_count: 88, first_year: 1996, last_year: 2024, lon: -2.575, lat: 51.463 },
];

export const SPECIES_INFO: Record<string, SpeciesInfo> = {
  'Erithacus rubecula': {
    scientific_name: 'Erithacus rubecula',
    common_name: 'Robin',
    has_image: true,
    image_url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f3/Erithacus_rubecula_with_cocked_head.jpg/320px-Erithacus_rubecula_with_cocked_head.jpg',
    image_licence: 'CC BY-SA',
    image_attribution: 'Francis C. Franklin (Wikimedia Commons)',
    image_source: 'wikipedia',
    description: 'The European robin is a small insectivorous passerine, familiar across gardens in the West of England and much of Europe.',
    description_source: 'wikipedia',
    description_licence: 'CC BY-SA 4.0',
    description_url: 'https://en.wikipedia.org/wiki/European_robin',
    fetched_at: '2026-07-06T00:00:00Z',
  },
  // A sensitive species with NO reusable image — exercises the placeholder path.
  'Lutra lutra': {
    scientific_name: 'Lutra lutra',
    common_name: 'Otter',
    has_image: false,
    image_url: null,
    image_licence: null,
    image_attribution: null,
    image_source: null,
    description: 'The Eurasian otter is a semi-aquatic mammal; its precise locations are shown only at a coarse resolution.',
    description_source: 'wikipedia',
    description_licence: 'CC BY-SA 4.0',
    description_url: 'https://en.wikipedia.org/wiki/Eurasian_otter',
    fetched_at: '2026-07-06T00:00:00Z',
  },
};

/** The cells as GeoJSON — use this as a MapLibre GeoJSON source while mocking. */
export const CELLS_GEOJSON = {
  type: 'FeatureCollection' as const,
  features: CELLS.map((c) => ({
    type: 'Feature' as const,
    properties: { ...c },
    geometry: { type: 'Point' as const, coordinates: [c.lon, c.lat] },
  })),
};
