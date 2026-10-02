// Typed functions for each apiContract endpoint. Thin wrappers over getJson + a schema.
import { getJson, type GetJsonOptions, type QueryParams } from "./client";
import {
  CellDistributionSchema,
  HealthSchema,
  ProvenanceSchema,
  RecordPageSchema,
  SpeciesDetailSchema,
  SpeciesListPageSchema,
  SummarySchema,
  type CellDistribution,
  type Health,
  type Provenance,
  type RecordPage,
  type SpeciesDetail,
  type SpeciesListPage,
  type SpeciesSort,
  type Summary,
} from "./schemas";

export interface SpeciesListParams extends QueryParams {
  q?: string;
  group?: string;
  sort?: SpeciesSort;
  page?: number;
  pageSize?: number;
}

export const getHealth = (options?: GetJsonOptions): Promise<Health> =>
  getJson("/health", HealthSchema, undefined, options);

export const getSpecies = (
  params?: SpeciesListParams,
  options?: GetJsonOptions,
): Promise<SpeciesListPage> => getJson("/species", SpeciesListPageSchema, params, options);

export const getSpeciesDetail = (
  speciesId: string,
  options?: GetJsonOptions,
): Promise<SpeciesDetail> =>
  getJson(`/species/${encodeURIComponent(speciesId)}`, SpeciesDetailSchema, undefined, options);

export const getDistributionCells = (
  params?: QueryParams,
  options?: GetJsonOptions,
): Promise<CellDistribution> =>
  getJson("/distribution/cells", CellDistributionSchema, params, options);

export const getRecords = (
  params?: QueryParams,
  options?: GetJsonOptions,
): Promise<RecordPage> => getJson("/records", RecordPageSchema, params, options);

export const getSummary = (
  params?: QueryParams,
  options?: GetJsonOptions,
): Promise<Summary> => getJson("/summary", SummarySchema, params, options);

export const getProvenance = (options?: GetJsonOptions): Promise<Provenance> =>
  getJson("/meta/provenance", ProvenanceSchema, undefined, options);
