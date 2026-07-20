// Shared, PII-free domain types. Inferred from the Zod contract so the types and the
// runtime validation can never drift. Import domain types from here across the app.
export type {
  Health,
  SpeciesListItem,
  SpeciesListPage,
  SpeciesDetail,
  SpeciesImage,
  RecordRow,
  RecordPage,
  GridCellFeature,
  CellCollection,
  Summary,
  Provenance,
  VerifiedStatus,
} from "../lib/api/schemas";

/** Discriminated-union async state — components never see raw undefined. */
export type AsyncState<T> =
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "empty" }
  | { status: "ready"; data: T };
