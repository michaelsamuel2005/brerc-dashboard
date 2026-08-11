// Hand-authored fixtures mirroring the required PUBLIC contract shape (derived from the
// 19-column main5 sample). By construction they contain NO Recorder1/BLISS/Eastings/
// Northings/Comments and NO sensitivity marker. Everything is SYNTHETIC demo data.
//
// Geographic honesty: each cell is a real Ordnance Survey 1 km square, its polygon
// computed by transforming the square's true EPSG:27700 corners to WGS84 — so the drawn
// geometry matches its grid reference and cells never overlap. Every reference is at or
// coarser than the 100 m public floor. The individual-records list is a small SAMPLE of
// the species' 186 records (the map/cell table carries the complete distribution).
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
    { speciesId: "anguis-fragilis", scientificName: "Anguis fragilis", commonName: "Slow-worm", group: "reptile", recordCount: 186, firstYear: 1994, lastYear: 2024, hasImage: false },
    { speciesId: "vipera-berus", scientificName: "Vipera berus", commonName: "Adder", group: "reptile", recordCount: 143, firstYear: 1996, lastYear: 2023, hasImage: false },
    { speciesId: "zootoca-vivipara", scientificName: "Zootoca vivipara", commonName: "Common Lizard", group: "reptile", recordCount: 402, firstYear: 1995, lastYear: 2024, hasImage: false },
    { speciesId: "erinaceus-europaeus", scientificName: "Erinaceus europaeus", commonName: "West European Hedgehog", group: "mammal", recordCount: 1206, firstYear: 1990, lastYear: 2024, hasImage: false },
  ],
  page: 1,
  pageSize: 20,
  total: 4,
} satisfies z.input<typeof SpeciesListPageSchema>;

// Photography is deferred (R3): the image is intentionally omitted so the designed,
// licensed-safe fallback is exercised. No fabricated author/licence metadata.
export const speciesDetailFixture = {
  speciesId: "anguis-fragilis",
  scientificName: "Anguis fragilis",
  commonName: "Slow-worm",
  group: "reptile",
  description:
    "A legless lizard, often mistaken for a snake, found in gardens, grassland and woodland edges across the West of England. It is protected in the UK against killing, injury and trade.",
  stats: { recordCount: 186, yearRange: [1994, 2024], verifiedCount: 178 },
} satisfies z.input<typeof SpeciesDetailSchema>;

// A SAMPLE of 8 individual records out of 186. Each grid reference is a 100 m square that
// falls inside one of the cells below; all are at or coarser than the 100 m public floor.
export const recordsFixture = {
  items: [
    { id: "5610349", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST585725", precisionMetres: 100, place: null, year: 2020, abundance: "12", recordType: "field record", verified: "Accepted – correct", source: "consultancy" },
    { id: "5610350", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST597728", precisionMetres: 100, place: null, year: 2021, abundance: "5", recordType: "reptile tin or mat", verified: "Accepted – considered correct", source: "recorder" },
    { id: "5610351", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST577735", precisionMetres: 100, place: null, year: 2019, abundance: "8", recordType: "field record", verified: "Accepted – correct", source: "consultancy" },
    { id: "5610352", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST607724", precisionMetres: 100, place: null, year: 2023, abundance: "3", recordType: "field record", verified: "Accepted – correct", source: "recorder" },
    { id: "5610353", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST586719", precisionMetres: 100, place: null, year: 2024, abundance: "2", recordType: "reptile survey", verified: "Accepted – considered correct", source: "recorder" },
    { id: "5610354", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST598736", precisionMetres: 100, place: null, year: 2018, abundance: "6", recordType: "field record", verified: "Accepted – correct", source: "consultancy" },
    { id: "5610355", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST614728", precisionMetres: 100, place: null, year: 2022, abundance: "4", recordType: "field record", verified: "Accepted – correct", source: "recorder" },
    { id: "5610356", scientificName: "Anguis fragilis", commonName: "Slow-worm", gridRef: "ST579745", precisionMetres: 100, place: null, year: 1996, abundance: "1", recordType: "field record", verified: "Accepted – correct", source: "consultancy" },
  ],
  page: 1,
  pageSize: 20,
  total: 186,
} satisfies z.input<typeof RecordPageSchema>;

// Real OS 1 km squares around south Bristol (EPSG:27700 corners → WGS84). Σ records = 186.
export const cellsFixture = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "Polygon", coordinates: [[[-2.605729, 51.445422], [-2.591341, 51.445495], [-2.591457, 51.454486], [-2.605849, 51.454413], [-2.605729, 51.445422]]] }, properties: { cellId: "ST5872", precisionMetres: 1000, recordCount: 58, verifiedCount: 55 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: [[[-2.591341, 51.445495], [-2.576953, 51.445567], [-2.577066, 51.454558], [-2.591457, 51.454486], [-2.591341, 51.445495]]] }, properties: { cellId: "ST5972", precisionMetres: 1000, recordCount: 44, verifiedCount: 42 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: [[[-2.620239, 51.454338], [-2.605849, 51.454413], [-2.605968, 51.463404], [-2.620361, 51.463329], [-2.620239, 51.454338]]] }, properties: { cellId: "ST5773", precisionMetres: 1000, recordCount: 31, verifiedCount: 30 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: [[[-2.576953, 51.445567], [-2.562565, 51.445637], [-2.562675, 51.454628], [-2.577066, 51.454558], [-2.576953, 51.445567]]] }, properties: { cellId: "ST6072", precisionMetres: 1000, recordCount: 22, verifiedCount: 21 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: [[[-2.605611, 51.436431], [-2.591225, 51.436504], [-2.591341, 51.445495], [-2.605729, 51.445422], [-2.605611, 51.436431]]] }, properties: { cellId: "ST5871", precisionMetres: 1000, recordCount: 15, verifiedCount: 14 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: [[[-2.591457, 51.454486], [-2.577066, 51.454558], [-2.57718, 51.463549], [-2.591574, 51.463477], [-2.591457, 51.454486]]] }, properties: { cellId: "ST5973", precisionMetres: 1000, recordCount: 9, verifiedCount: 9 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: [[[-2.562565, 51.445637], [-2.548176, 51.445705], [-2.548284, 51.454696], [-2.562675, 51.454628], [-2.562565, 51.445637]]] }, properties: { cellId: "ST6172", precisionMetres: 1000, recordCount: 4, verifiedCount: 4 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: [[[-2.620361, 51.463329], [-2.605968, 51.463404], [-2.606087, 51.472395], [-2.620483, 51.47232], [-2.620361, 51.463329]]] }, properties: { cellId: "ST5774", precisionMetres: 1000, recordCount: 3, verifiedCount: 3 } },
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
