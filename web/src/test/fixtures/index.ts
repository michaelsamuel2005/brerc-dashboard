// Hand-authored fixtures mirroring the required PUBLIC contract shape (derived from the
// 19-column main5 sample). By construction they contain NO Recorder1/BLISS/Eastings/
// Northings/Comments and NO sensitivity marker. Coordinates are illustrative 1 km cells
// around the Bristol area for one species (Slow-worm) — synthetic demo data, not real.
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
  description:
    "A legless lizard, often mistaken for a snake, found in gardens, grassland and woodland edges across the West of England. It is protected in the UK against killing, injury and trade.",
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
    { id: "5610349", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST5748", precisionMetres: 1000, place: "Almondsbury area", year: 2020, abundance: "13", recordType: "field record", verified: "Accepted – correct", source: "consultancy" },
    { id: "5610350", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST5848", precisionMetres: 1000, place: null, year: 2021, abundance: "5", recordType: "reptile tin or mat", verified: "Accepted – considered correct", source: "recorder" },
    { id: "5610351", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST594745", precisionMetres: 100, place: null, year: 2022, abundance: "3", recordType: "field record", verified: "Accepted – correct", source: "recorder" },
    { id: "5610352", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST60498827", precisionMetres: 10, place: null, year: 2023, abundance: "1", recordType: "field record", verified: "Accepted – correct", source: "recorder" },
    { id: "5610353", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST5645", precisionMetres: 1000, place: "Kingswood area", year: 2019, abundance: "8", recordType: "field record", verified: "Accepted – correct", source: "consultancy" },
    { id: "5610354", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST594455", precisionMetres: 100, place: null, year: 2024, abundance: "2", recordType: "reptile survey", verified: "Accepted – considered correct", source: "recorder" },
    { id: "5610355", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST5747", precisionMetres: 1000, place: "Filton area", year: 2018, abundance: "6", recordType: "field record", verified: "Accepted – correct", source: "consultancy" },
    { id: "5610356", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST585480", precisionMetres: 100, place: null, year: 2022, abundance: "4", recordType: "field record", verified: "Accepted – considered correct", source: "recorder" },
  ],
  page: 1,
  pageSize: 20,
  total: 8,
} satisfies z.input<typeof RecordPageSchema>;

// Build a closed 1 km-ish polygon ring from a south-west corner (display only).
function cell(lng: number, lat: number): number[][][] {
  const dLng = 0.0144;
  const dLat = 0.009;
  return [[[lng, lat], [lng + dLng, lat], [lng + dLng, lat + dLat], [lng, lat + dLat], [lng, lat]]];
}

export const cellsFixture = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "Polygon", coordinates: cell(-2.600, 51.480) }, properties: { cellId: "ST5748", precisionMetres: 1000, recordCount: 52, verifiedCount: 49 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: cell(-2.586, 51.485) }, properties: { cellId: "ST5848", precisionMetres: 1000, recordCount: 33, verifiedCount: 31 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: cell(-2.571, 51.470) }, properties: { cellId: "ST5947", precisionMetres: 1000, recordCount: 18, verifiedCount: 17 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: cell(-2.600, 51.460) }, properties: { cellId: "ST5746", precisionMetres: 1000, recordCount: 9, verifiedCount: 8 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: cell(-2.550, 51.490) }, properties: { cellId: "ST6049", precisionMetres: 1000, recordCount: 44, verifiedCount: 42 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: cell(-2.614, 51.455) }, properties: { cellId: "ST5645", precisionMetres: 1000, recordCount: 4, verifiedCount: 4 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: cell(-2.564, 51.455) }, properties: { cellId: "ST5945", precisionMetres: 1000, recordCount: 21, verifiedCount: 20 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: cell(-2.590, 51.475) }, properties: { cellId: "ST5747", precisionMetres: 1000, recordCount: 12, verifiedCount: 11 } },
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
