// Hand-authored fixtures mirroring the required PUBLIC contract shape (derived from the
// 19-column main5 sample). By construction they contain NO Recorder1/BLISS/Eastings/
// Northings/Comments and NO sensitivity marker. One record is a generalised (1km),
// blended, UNLABELLED sensitive-taxon example — indistinguishable from an ordinary cell.
import { z } from "zod";
import {
  CellCollectionSchema,
  HealthSchema,
  ProvenanceSchema,
  RecordPageSchema,
  SpeciesDetailSchema,
  SpeciesListPageSchema,
  SummarySchema,
} from "../../lib/api/schemas";

export const healthFixture = { status: "ok", version: "0.1.0" } satisfies z.input<typeof HealthSchema>;

export const speciesListFixture = {
  items: [
    { speciesId: "anguis-fragilis", scientificName: "Anguis fragilis", commonName: "Slow-worm", group: "reptile", recordCount: 918, firstYear: 1994, lastYear: 2024, hasImage: true },
    { speciesId: "vipera-berus", scientificName: "Vipera berus", commonName: "Adder", group: "reptile", recordCount: 143, firstYear: 1996, lastYear: 2023, hasImage: true },
    { speciesId: "zootoca-vivipara", scientificName: "Zootoca vivipara", commonName: "Common Lizard", group: "reptile", recordCount: 402, firstYear: 1995, lastYear: 2024, hasImage: false },
    { speciesId: "erinaceus-europaeus", scientificName: "Erinaceus europaeus", commonName: "West European Hedgehog", group: "mammal", recordCount: 1206, firstYear: 1990, lastYear: 2024, hasImage: true },
  ],
  page: 1,
  pageSize: 20,
  total: 4,
} satisfies z.input<typeof SpeciesListPageSchema>;

export const speciesDetailFixture = {
  speciesId: "anguis-fragilis",
  scientificName: "Anguis fragilis",
  commonName: "Slow-worm",
  group: "reptile",
  description: "A legless lizard, often mistaken for a snake, found in gardens, grassland and woodland edges across the West of England.",
  image: {
    url: "https://upload.wikimedia.org/wikipedia/commons/thumb/anguis.jpg",
    author: "Jane Naturalist",
    licence: "CC BY-SA 4.0",
    licenceUrl: "https://creativecommons.org/licenses/by-sa/4.0/",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Anguis_fragilis.jpg",
    alt: "A bronze-coloured slow-worm coiled on a mossy log.",
  },
  stats: { recordCount: 918, yearRange: [1994, 2024], verifiedCount: 902 },
} satisfies z.input<typeof SpeciesDetailSchema>;

export const recordsFixture = {
  items: [
    { id: "5610349", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST5972", precisionMetres: 1000, place: "Tytherington area", year: 2020, abundance: "13", recordType: "field record", verified: "Accepted – correct", source: "consultancy" },
    { id: "5610350", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST597727", precisionMetres: 100, place: null, year: 2021, abundance: "3", recordType: "reptile tin or mat", verified: "Accepted – considered correct", source: "recorder" },
    { id: "5610351", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST59722885", precisionMetres: 10, place: null, year: 2022, abundance: "1", recordType: "field record", verified: "Accepted – correct", source: "recorder" },
  ],
  page: 1,
  pageSize: 20,
  total: 3,
} satisfies z.input<typeof RecordPageSchema>;

export const cellsFixture = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [[[-2.51, 51.61], [-2.50, 51.61], [-2.50, 51.62], [-2.51, 51.62], [-2.51, 51.61]]] },
      properties: { cellId: "ST5972", precisionMetres: 1000, recordCount: 41, verifiedCount: 39 },
    },
    {
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [[[-2.60, 51.45], [-2.59, 51.45], [-2.59, 51.46], [-2.60, 51.46], [-2.60, 51.45]]] },
      properties: { cellId: "ST5845", precisionMetres: 1000, recordCount: 12, verifiedCount: 12 },
    },
  ],
} satisfies z.input<typeof CellCollectionSchema>;

export const summaryFixture = {
  totalRecords: 4291,
  totalSpecies: 5,
  yearRange: { min: 1990, max: 2024 },
  recordsByYear: [
    { year: 2020, count: 402 },
    { year: 2021, count: 511 },
    { year: 2022, count: 634 },
    { year: 2023, count: 700 },
    { year: 2024, count: 588 },
  ],
  topGroups: [
    { group: "mammal", count: 1206 },
    { group: "reptile", count: 1463 },
  ],
  coverageCaveat: "Records reflect where people looked, not true distribution or abundance.",
} satisfies z.input<typeof SummarySchema>;

export const provenanceFixture = {
  lastUpdated: "2026-07-20",
  recordTotal: 4291,
  sources: ["BRERC verified records", "Consultancy submissions"],
  coverageCaveats: [
    "Recording effort is uneven across the region.",
    "Absence of records does not mean absence of a species.",
  ],
  sensitivityPolicy: {
    generalisationTiersMetres: [1000, 10000],
    appliesToProtectedTaxa: true,
    note: "Sensitive-species locations are generalised server-side and blended into the ordinary grid.",
  },
  attributions: [{ label: "BRERC", url: "https://www.brerc.org.uk", licence: "CC BY-NC 4.0" }],
} satisfies z.input<typeof ProvenanceSchema>;
