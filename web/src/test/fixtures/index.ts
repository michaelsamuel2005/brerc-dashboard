// Hand-authored fixtures mirroring the required PUBLIC contract shape. By construction they
// contain NO Recorder1/BLISS/easting(s)/northing(s)/Comments and NO sensitive/sensitivity marker.
// Everything is SYNTHETIC demo data.
//
// SINGLE SOURCE OF TRUTH: `cellYearMatrix` (records per grid square per year). The cell
// totals, the year series, the species statistics and every year-filtered view are all
// DERIVED from it, so the map, the chart and the tables reconcile exactly at any filter.
// Distribution cells carry only an ID + counts — the client derives each square's polygon
// from the (validated) grid ID. Every reference is at or coarser than the 100 m floor.
import { z } from "zod";
import {
  CellDistributionSchema,
  HealthSchema,
  ProvenanceSchema,
  RecordPageSchema,
  SpeciesDetailSchema,
  SpeciesListPageSchema,
  SummarySchema,
  type GridCell,
  type SpeciesSort,
} from "../../lib/api/schemas";

type CellYearData = Record<string, Record<number, number>>;

interface DemoSpeciesDefinition {
  speciesId: string;
  slug: string;
  scientificName: string;
  commonName: string | null;
  group: string;
  description?: string;
  matrix: CellYearData;
  unverified: CellYearData;
}

/** Records per grid square per year (the source of truth). */
export const cellYearMatrix: Record<string, Record<number, number>> = {
  "ST5872": { 1995: 1, 1997: 1, 1998: 1, 1999: 1, 2000: 2, 2001: 1, 2002: 1, 2003: 1, 2004: 1, 2005: 1, 2006: 1, 2007: 2, 2008: 2, 2009: 3, 2010: 3, 2011: 3, 2012: 3, 2013: 2, 2014: 3, 2015: 1, 2016: 3, 2017: 2, 2018: 4, 2019: 2, 2020: 2, 2021: 2, 2022: 4, 2023: 4, 2024: 1 },
  "ST5972": { 1996: 1, 1997: 1, 1998: 1, 1999: 1, 2000: 1, 2001: 1, 2002: 1, 2003: 1, 2004: 1, 2005: 1, 2006: 1, 2007: 2, 2008: 1, 2009: 1, 2010: 2, 2011: 2, 2012: 2, 2013: 1, 2014: 2, 2015: 3, 2016: 2, 2017: 1, 2018: 1, 2019: 2, 2020: 3, 2021: 3, 2022: 1, 2023: 1, 2024: 3 },
  "ST5773": { 1996: 1, 1997: 1, 1999: 1, 2001: 1, 2002: 1, 2003: 1, 2004: 1, 2005: 1, 2006: 1, 2008: 1, 2009: 1, 2010: 1, 2011: 1, 2012: 1, 2013: 1, 2014: 2, 2015: 2, 2016: 1, 2017: 1, 2018: 1, 2019: 2, 2020: 1, 2021: 1, 2022: 1, 2023: 2, 2024: 2 },
  "ST6072": { 1999: 1, 2002: 1, 2004: 1, 2005: 1, 2006: 1, 2008: 1, 2009: 1, 2010: 1, 2011: 1, 2012: 1, 2013: 1, 2015: 1, 2016: 1, 2017: 1, 2018: 1, 2019: 1, 2020: 1, 2021: 1, 2022: 1, 2023: 2, 2024: 1 },
  "ST5871": { 2001: 1, 2004: 1, 2006: 1, 2008: 1, 2011: 1, 2012: 1, 2015: 1, 2016: 1, 2017: 1, 2018: 1, 2019: 1, 2020: 1, 2021: 1, 2023: 1, 2024: 1 },
  "ST5973": { 2007: 1, 2009: 1, 2013: 1, 2015: 1, 2018: 1, 2020: 1, 2022: 1, 2023: 1, 2024: 1 },
  "ST6172": { 2014: 1, 2018: 1, 2021: 1, 2023: 1 },
  "ST5774": { 2017: 1, 2020: 1, 2022: 1 },
};

/** Records that are NOT verified, per square per year (a subset of the matrix). */
export const cellYearUnverified: Record<string, Record<number, number>> = {
  "ST5871": { 2008: 1 },
  "ST5973": { 2015: 1 },
  "ST5872": { 1998: 1, 2001: 1, 2016: 1 },
  "ST5773": { 2016: 1 },
  "ST5972": { 2022: 1 },
  "ST6072": { 2011: 1 },
};

const cellIds = Object.keys(cellYearMatrix);

/** Every year that has at least one record, ascending. */
export const YEARS: number[] = Array.from(
  new Set(cellIds.flatMap((id) => Object.keys(cellYearMatrix[id] ?? {}).map(Number))),
).sort((a, b) => a - b);

/** Cells for a given year (or all years when omitted). Squares with no records are dropped. */
function cellsFrom(matrix: CellYearData, unverified: CellYearData, year?: number): GridCell[] {
  return Object.keys(matrix)
    .map((cellId) => {
      const years = matrix[cellId] ?? {};
      const un = unverified[cellId] ?? {};
      const pick = (src: Record<number, number>) =>
        year === undefined
          ? Object.values(src).reduce((a, b) => a + b, 0)
          : src[year] ?? 0;
      const recordCount = pick(years);
      return { cellId, precisionMetres: 1000, recordCount, verifiedCount: recordCount - pick(un) };
    })
    .filter((c) => c.recordCount > 0);
}

export function cellsFor(year?: number): GridCell[] {
  return cellsFrom(cellYearMatrix, cellYearUnverified, year);
}

/** The records-by-year series (derived from the same matrix as the cells). */
function recordsByYearFrom(matrix: CellYearData): { year: number; count: number }[] {
  const years = Array.from(
    new Set(Object.values(matrix).flatMap((cell) => Object.keys(cell).map(Number))),
  ).sort((a, b) => a - b);
  return years.map((year) => ({
    year,
    count: Object.keys(matrix).reduce((n, id) => n + (matrix[id]?.[year] ?? 0), 0),
  }));
}

export function recordsByYear(): { year: number; count: number }[] {
  return recordsByYearFrom(cellYearMatrix);
}

const adderCellYearMatrix: CellYearData = {
  "ST5673": { 1998: 3, 2004: 5, 2012: 8, 2020: 10, 2024: 7 },
  "ST5773": { 2001: 4, 2009: 6, 2018: 9, 2024: 5 },
  "ST5873": { 1999: 2, 2010: 7, 2016: 8, 2023: 11 },
};

const commonLizardCellYearMatrix: CellYearData = {
  "ST5772": { 1997: 6, 2005: 9, 2012: 15, 2019: 18, 2024: 12 },
  "ST5872": { 1995: 4, 2002: 8, 2010: 16, 2018: 21, 2023: 14 },
  "ST5972": { 2000: 7, 2008: 12, 2016: 17, 2022: 20 },
  "ST6072": { 2003: 5, 2011: 10, 2020: 15, 2024: 9 },
};

const hedgehogCellYearMatrix: CellYearData = {
  "ST5672": { 1990: 12, 2000: 22, 2010: 34, 2020: 45, 2024: 28 },
  "ST5772": { 1993: 10, 2003: 25, 2013: 38, 2023: 51 },
  "ST5872": { 1995: 16, 2005: 29, 2015: 42, 2024: 35 },
  "ST5972": { 1998: 14, 2008: 27, 2018: 44, 2022: 39 },
  "ST6072": { 2001: 18, 2011: 31, 2021: 47, 2024: 30 },
};

// These identifiers are deliberately synthetic opaque strings. Production values come
// from BRERC SPECIES_NO; the human-readable URL slug is a separate field by contract.
export const DEFAULT_SPECIES_ID = "DEMO-001";
export const DEFAULT_SPECIES_SLUG = "anguis-fragilis";

const demoSpecies: readonly DemoSpeciesDefinition[] = [
  {
    speciesId: DEFAULT_SPECIES_ID,
    slug: DEFAULT_SPECIES_SLUG,
    scientificName: "Anguis fragilis",
    commonName: "Slow-worm",
    group: "reptile",
    description:
      "A legless lizard, often mistaken for a snake, found in gardens, grassland and woodland edges across the West of England. It is protected in the UK against killing, injury and trade.",
    matrix: cellYearMatrix,
    unverified: cellYearUnverified,
  },
  {
    speciesId: "DEMO-002",
    slug: "vipera-berus",
    scientificName: "Vipera berus",
    commonName: "Adder",
    group: "reptile",
    matrix: adderCellYearMatrix,
    unverified: {},
  },
  {
    speciesId: "DEMO-003",
    slug: "zootoca-vivipara",
    scientificName: "Zootoca vivipara",
    commonName: "Common lizard",
    group: "reptile",
    matrix: commonLizardCellYearMatrix,
    unverified: {},
  },
  {
    speciesId: "DEMO-004",
    slug: "erinaceus-europaeus",
    scientificName: "Erinaceus europaeus",
    commonName: "West European hedgehog",
    group: "mammal",
    matrix: hedgehogCellYearMatrix,
    unverified: {},
  },
];

const demoSpeciesById = new Map(demoSpecies.map((species) => [species.speciesId, species]));

const groupLabels: Readonly<Record<string, string>> = {
  mammal: "Mammals",
  reptile: "Reptiles",
};

/** One atomic synthetic release shared by every mock API response. */
export const fixtureReleaseIdentity: { releaseId: string; datasetVersion: string } = {
  releaseId: "00000000-0000-4000-8000-000000000001",
  datasetVersion: "fixture-contract-v1",
};

export const speciesGroupFacets = Array.from(new Set(demoSpecies.map((species) => species.group)))
  .sort((a, b) => (groupLabels[a] ?? a).localeCompare(groupLabels[b] ?? b, "en-GB"))
  .map((value) => ({
    value,
    label: groupLabels[value] ?? value,
    speciesCount: demoSpecies.filter((species) => species.group === value).length,
  }));

function definitionStats(definition: DemoSpeciesDefinition) {
  const cells = cellsFrom(definition.matrix, definition.unverified);
  const years = recordsByYearFrom(definition.matrix).map((item) => item.year);
  return {
    recordCount: cells.reduce((total, cell) => total + cell.recordCount, 0),
    verifiedCount: cells.reduce((total, cell) => total + (cell.verifiedCount ?? 0), 0),
    firstYear: years[0] ?? null,
    lastYear: years[years.length - 1] ?? null,
  };
}

export const speciesListItems = demoSpecies.map((definition) => {
  const stats = definitionStats(definition);
  return {
    speciesId: definition.speciesId,
    slug: definition.slug,
    scientificName: definition.scientificName,
    commonName: definition.commonName,
    group: definition.group,
    recordCount: stats.recordCount,
    firstYear: stats.firstYear,
    lastYear: stats.lastYear,
    hasImage: false,
  };
});

export interface SpeciesDirectoryRequest {
  q?: string;
  group?: string;
  sort?: SpeciesSort;
  page?: number;
  pageSize?: number;
}

export function buildSpeciesListPage({
  q = "",
  group,
  sort = "name-asc",
  page = 1,
  pageSize = 20,
}: SpeciesDirectoryRequest = {}) {
  if (!Number.isInteger(page) || page < 1 || !Number.isInteger(pageSize) || pageSize < 1) {
    throw new RangeError("page and pageSize must be positive integers");
  }
  const term = q.trim().toLocaleLowerCase("en-GB");
  const filtered = speciesListItems.filter((species) => {
    const matchesGroup = group === undefined || species.group === group;
    const matchesSearch =
      term === "" ||
      species.scientificName.toLocaleLowerCase("en-GB").includes(term) ||
      (species.commonName?.toLocaleLowerCase("en-GB").includes(term) ?? false);
    return matchesGroup && matchesSearch;
  });

  const displayName = (species: (typeof speciesListItems)[number]) =>
    species.commonName ?? species.scientificName;
  const byDisplayName = (
    a: (typeof speciesListItems)[number],
    b: (typeof speciesListItems)[number],
  ) => displayName(a).localeCompare(displayName(b), "en-GB") || a.speciesId.localeCompare(b.speciesId, "en-GB");
  const ordered = [...filtered].sort((a, b) => {
    if (sort === "records-desc") return b.recordCount - a.recordCount || byDisplayName(a, b);
    if (sort === "latest-record-desc") {
      return (b.lastYear ?? -Infinity) - (a.lastYear ?? -Infinity) || byDisplayName(a, b);
    }
    if (sort === "scientific-name-asc") {
      return a.scientificName.localeCompare(b.scientificName, "en-GB") || a.speciesId.localeCompare(b.speciesId, "en-GB");
    }
    return byDisplayName(a, b);
  });

  const start = (page - 1) * pageSize;
  return {
    ...fixtureReleaseIdentity,
    items: ordered.slice(start, start + pageSize),
    page,
    pageSize,
    total: ordered.length,
    facets: { groups: speciesGroupFacets },
  };
}

export function cellsForSpecies(speciesId: string, year?: number): GridCell[] {
  const definition = demoSpeciesById.get(speciesId);
  return definition ? cellsFrom(definition.matrix, definition.unverified, year) : [];
}

export function recordsByYearForSpecies(speciesId: string): { year: number; count: number }[] {
  const definition = demoSpeciesById.get(speciesId);
  return definition ? recordsByYearFrom(definition.matrix) : [];
}

export function speciesDetailFor(speciesId: string) {
  const definition = demoSpeciesById.get(speciesId);
  if (!definition) return null;
  const stats = definitionStats(definition);
  const yearRange =
    stats.firstYear === null || stats.lastYear === null
      ? null
      : ([stats.firstYear, stats.lastYear] as [number, number]);
  return {
    ...fixtureReleaseIdentity,
    speciesId: definition.speciesId,
    slug: definition.slug,
    scientificName: definition.scientificName,
    commonName: definition.commonName,
    group: definition.group,
    ...(definition.description
      ? {
          description: definition.description,
          descriptionSource: {
            label: "Synthetic demonstration content",
            approvalReference: "synthetic-fixture-only",
          },
        }
      : {}),
    imagePublication: "fallback-only" as const,
    stats: {
      recordCount: stats.recordCount,
      yearRange,
      verificationAvailable: true,
      verifiedCount: stats.verifiedCount,
    },
  };
}

function requiredSpeciesDetailFor(speciesId: string) {
  const detail = speciesDetailFor(speciesId);
  if (!detail) throw new Error(`Missing synthetic species detail for ${speciesId}`);
  return detail;
}

export function speciesSummaryFor(speciesId: string) {
  const definition = demoSpeciesById.get(speciesId);
  const detail = speciesDetailFor(speciesId);
  if (!definition || !detail) return null;
  return {
    ...fixtureReleaseIdentity,
    totalRecords: detail.stats.recordCount,
    totalSpecies: 1,
    yearRange: detail.stats.yearRange
      ? { min: detail.stats.yearRange[0], max: detail.stats.yearRange[1] }
      : null,
    recordsByYear: recordsByYearFrom(definition.matrix),
    topGroups: [{ group: definition.group, count: detail.stats.recordCount }],
    coverageCaveat: "Counts show recording effort — how often people looked and reported — not abundance.",
  };
}

function requiredSpeciesSummaryFor(speciesId: string) {
  const summary = speciesSummaryFor(speciesId);
  if (!summary) throw new Error(`Missing synthetic species summary for ${speciesId}`);
  return summary;
}

function publicGridRef(cellId: string): string {
  return `${cellId.slice(0, 4)}5${cellId.slice(4)}5`;
}

export function recordsForSpecies(
  speciesId: string,
  year?: number,
  page = 1,
  pageSize = 20,
) {
  if (!Number.isInteger(page) || page < 1 || !Number.isInteger(pageSize) || pageSize < 1) {
    throw new RangeError("page and pageSize must be positive integers");
  }
  const definition = demoSpeciesById.get(speciesId);
  const publication = {
    mode: "individual-records" as const,
    fields: {
      abundance: false,
      place: false,
      recordType: true,
      verification: true,
    },
  };
  if (!definition) {
    return { ...fixtureReleaseIdentity, publication, items: [], page, pageSize, total: 0 };
  }
  const matchingRecords = Object.entries(definition.matrix)
    .flatMap(([cellId, years]) =>
      Object.entries(years)
        .map(([sampleYear, count]) => [Number(sampleYear), count] as const)
        .sort((a, b) => b[0] - a[0])
        .flatMap(([sampleYear, count]) => {
          const unverifiedCount = definition.unverified[cellId]?.[sampleYear] ?? 0;
          return Array.from({ length: count }, (_, index) => ({
            id: `${definition.speciesId}-${cellId}-${sampleYear}-${index + 1}`,
            scientificName: definition.scientificName,
            commonName: definition.commonName,
            gridRef: publicGridRef(cellId),
            precisionMetres: 100,
            place: null,
            year: sampleYear,
            recordType: "field record",
            verified: index < unverifiedCount ? "Awaiting verification" : "Accepted – correct",
            source: "synthetic demonstration data",
          }));
        }),
    )
    .filter((record) => year === undefined || record.year === year);
  const start = (page - 1) * pageSize;
  return {
    ...fixtureReleaseIdentity,
    publication,
    items: matchingRecords.slice(start, start + pageSize),
    page,
    pageSize,
    total: matchingRecords.length,
  };
}

export const overallRecordsByYear = Array.from(
  demoSpecies.reduce((years, species) => {
    for (const { year, count } of recordsByYearFrom(species.matrix)) {
      years.set(year, (years.get(year) ?? 0) + count);
    }
    return years;
  }, new Map<number, number>()),
  ([year, count]) => ({ year, count }),
).sort((a, b) => a.year - b.year);

const OVERALL_TOTAL_RECORDS = overallRecordsByYear.reduce((total, entry) => total + entry.count, 0);
const overallFirstYear = overallRecordsByYear[0]?.year ?? null;
const overallLastYear = overallRecordsByYear[overallRecordsByYear.length - 1]?.year ?? null;
const overallTopGroups = Array.from(
  demoSpecies.reduce((groups, species) => {
    groups.set(species.group, (groups.get(species.group) ?? 0) + definitionStats(species).recordCount);
    return groups;
  }, new Map<string, number>()),
  ([group, count]) => ({ group, count }),
).sort((a, b) => b.count - a.count || a.group.localeCompare(b.group, "en-GB"));

export const healthFixture = { status: "ok", version: "0.1.0" } satisfies z.input<typeof HealthSchema>;

export const speciesListFixture = buildSpeciesListPage() satisfies z.input<typeof SpeciesListPageSchema>;

// Photography deferred (R3): image omitted so the designed fallback is exercised.
export const speciesDetailFixture = requiredSpeciesDetailFor(DEFAULT_SPECIES_ID) satisfies z.input<typeof SpeciesDetailSchema>;

// Published synthetic individual records, each at a year that square genuinely has
// and at a 100 m reference inside it.
export const recordsFixture = recordsForSpecies(DEFAULT_SPECIES_ID) satisfies z.input<typeof RecordPageSchema>;

/** Honest response when BRERC approves aggregates but not individual occurrence rows. */
export const aggregateOnlyRecordsFixture = {
  ...fixtureReleaseIdentity,
  publication: {
    mode: "aggregates-only",
    fields: {
      abundance: false,
      place: false,
      recordType: false,
      verification: false,
    },
  },
  items: [],
  page: 1,
  pageSize: 20,
  total: 0,
} satisfies z.input<typeof RecordPageSchema>;

export const cellsFixture = {
  ...fixtureReleaseIdentity,
  verificationAvailable: true,
  cells: cellsFor(),
} satisfies z.input<typeof CellDistributionSchema>;

/** Species-scoped summary — the chart's data, derived from the same matrix. */
export const speciesSummaryFixture = requiredSpeciesSummaryFor(DEFAULT_SPECIES_ID) satisfies z.input<typeof SummarySchema>;

export const summaryFixture = {
  ...fixtureReleaseIdentity,
  totalRecords: OVERALL_TOTAL_RECORDS,
  totalSpecies: demoSpecies.length,
  yearRange:
    overallFirstYear === null || overallLastYear === null
      ? null
      : { min: overallFirstYear, max: overallLastYear },
  recordsByYear: overallRecordsByYear,
  topGroups: overallTopGroups,
  coverageCaveat: "Records reflect where people looked, not true distribution or abundance.",
} satisfies z.input<typeof SummarySchema>;

export const provenanceFixture = {
  ...fixtureReleaseIdentity,
  lastUpdated: "2026-07-20",
  recordTotal: OVERALL_TOTAL_RECORDS,
  sources: ["BRERC verified records", "Consultancy submissions"],
  coverageCaveats: [
    "Recording effort is uneven across the region.",
    "Absence of records does not mean absence of a species.",
  ],
  sensitivityPolicy: {
    protectedRecordsMode: "withheld",
    publishedLocationTiersMetres: [1000, 10000],
    note: "Records requiring sensitive-record protection are withheld from the public release.",
  },
  attributions: [{ label: "BRERC", url: "https://www.brerc.org.uk", licence: "CC BY-NC 4.0" }],
} satisfies z.input<typeof ProvenanceSchema>;
