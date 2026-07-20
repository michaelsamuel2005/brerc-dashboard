// Typed functions for each apiContract endpoint. Thin wrappers over getJson + a schema.
import { getJson, type QueryParams } from "./client";
import {
  CellCollectionSchema,
  HealthSchema,
  ProvenanceSchema,
  RecordPageSchema,
  SpeciesDetailSchema,
  SpeciesListPageSchema,
  SummarySchema,
  type CellCollection,
  type Health,
  type Provenance,
  type RecordPage,
  type SpeciesDetail,
  type SpeciesListPage,
  type Summary,
} from "./schemas";

export const getHealth = (): Promise<Health> => getJson("/health", HealthSchema);

export const getSpecies = (params?: QueryParams): Promise<SpeciesListPage> =>
  getJson("/species", SpeciesListPageSchema, params);

export const getSpeciesDetail = (speciesId: string): Promise<SpeciesDetail> =>
  getJson(`/species/${encodeURIComponent(speciesId)}`, SpeciesDetailSchema);

export const getDistributionCells = (params?: QueryParams): Promise<CellCollection> =>
  getJson("/distribution/cells", CellCollectionSchema, params);

export const getRecords = (params?: QueryParams): Promise<RecordPage> =>
  getJson("/records", RecordPageSchema, params);

export const getSummary = (params?: QueryParams): Promise<Summary> =>
  getJson("/summary", SummarySchema, params);

export const getProvenance = (): Promise<Provenance> => getJson("/meta/provenance", ProvenanceSchema);
