// ---------------------------------------------------------------------------
// Zod schemas = the SINGLE SOURCE OF TRUTH for the API contract (PLAN apiContract).
// Every schema is .strict(): any unexpected key (a leaked Recorder1 / BLISS / Eastings /
// Northings / Comments / sensitivity marker) makes the parse FAIL LOUDLY. This is the
// client-side C2 net (server-side generalisation is the fix).
//
// Runtime safety gates (run on every parsed response, real API included):
//   - a record's grid reference must resolve to EXACTLY its precisionMetres;
//   - a distribution cell's cellId must resolve to EXACTLY its precisionMetres — the map
//     derives cell geometry from the ID, so a mislabelled/precise polygon cannot be sent;
//   - every public location is at or coarser than the 100 m floor; URLs must be https.
// Public-safe domain types are inferred from these schemas so they cannot drift.
// ---------------------------------------------------------------------------
import { z } from "zod";
import { gridRefPrecisionMetres } from "../geo/gridref";

/** Coarsest allowed public resolution. Nothing finer may reach the client (C2 floor). */
export const PUBLIC_MIN_PRECISION_METRES = 100;

/** Normalise the raw `verified` string into an enum. Order matters: a negative verdict
 *  ("Rejected – not accepted") must never be read as accepted, so reject is tested first. */
export function normaliseVerified(raw: string): "accepted" | "unconfirmed" | "rejected" | "unknown" {
  const s = raw.toLowerCase();
  if (s.includes("reject")) return "rejected";
  if (s.includes("unconfirm") || s.includes("pending") || s.includes("unverified") || s.includes("not verified")) return "unconfirmed";
  if (s.includes("accept")) return "accepted";
  return "unknown";
}

/** A URL that must be https — rejects javascript:, data:, and other unsafe schemes. */
const httpsUrl = z
  .string()
  .url()
  .refine(
    (u) => {
      try {
        return new URL(u).protocol === "https:";
      } catch {
        return false;
      }
    },
    { message: "URL must use https" },
  );

export const HealthSchema = z.object({ status: z.literal("ok"), version: z.string() }).strict();

export const SpeciesListItemSchema = z
  .object({
    speciesId: z.string().min(1),
    scientificName: z.string().min(1),
    commonName: z.string().nullable(),
    group: z.string(),
    recordCount: z.number().int().nonnegative(),
    firstYear: z.number().int().nullable(),
    lastYear: z.number().int().nullable(),
    hasImage: z.boolean(),
  })
  .strict();

export const SpeciesListPageSchema = z
  .object({
    items: z.array(SpeciesListItemSchema),
    page: z.number().int().positive(),
    pageSize: z.number().int().positive(),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const SpeciesImageSchema = z
  .object({
    url: httpsUrl,
    author: z.string().min(1),
    licence: z.string().min(1),
    licenceUrl: httpsUrl,
    sourceUrl: httpsUrl,
    alt: z.string().min(1),
  })
  .strict();

export const SpeciesDetailSchema = z
  .object({
    speciesId: z.string().min(1),
    scientificName: z.string().min(1),
    commonName: z.string().nullable(),
    group: z.string(),
    description: z.string().optional(),
    image: SpeciesImageSchema.optional(),
    stats: z
      .object({
        recordCount: z.number().int().nonnegative(),
        yearRange: z.tuple([z.number().int(), z.number().int()]),
        verifiedCount: z.number().int().nonnegative(),
      })
      .strict(),
  })
  .strict();

export const RecordRowSchema = z
  .object({
    id: z.string().min(1),
    scientificName: z.string().min(1),
    commonName: z.string().nullable(),
    gridRef: z.string().min(1),
    precisionMetres: z.number().int().min(PUBLIC_MIN_PRECISION_METRES),
    place: z.string().nullable(),
    year: z.number().int(),
    abundance: z.string().nullable().optional(),
    recordType: z.string().nullable().optional(),
    verified: z.string().transform(normaliseVerified),
    source: z.string(),
  })
  .strict()
  .superRefine((row, ctx) => {
    const derived = gridRefPrecisionMetres(row.gridRef);
    if (derived === null) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["gridRef"], message: `Unparseable grid reference: ${row.gridRef}` });
      return;
    }
    if (derived !== row.precisionMetres) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["precisionMetres"],
        message: `precisionMetres ${row.precisionMetres} does not match grid reference ${row.gridRef} (${derived} m)`,
      });
    }
  });

export const RecordPageSchema = z
  .object({
    items: z.array(RecordRowSchema),
    page: z.number().int().positive(),
    pageSize: z.number().int().positive(),
    total: z.number().int().nonnegative(),
  })
  .strict();

// A distribution cell carries only an ID + counts; the CLIENT derives the polygon from the
// (validated) cellId. So the geometry always matches the ID — a precise polygon cannot be
// mislabelled as a coarse cell. cellId must resolve to exactly precisionMetres (≥ 100 m).
export const GridCellSchema = z
  .object({
    cellId: z.string().min(1),
    precisionMetres: z.number().int().min(PUBLIC_MIN_PRECISION_METRES),
    recordCount: z.number().int().nonnegative(),
    verifiedCount: z.number().int().nonnegative().optional(),
  })
  .strict()
  .superRefine((c, ctx) => {
    const derived = gridRefPrecisionMetres(c.cellId);
    if (derived === null) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["cellId"], message: `Unparseable grid reference: ${c.cellId}` });
    } else if (derived !== c.precisionMetres) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["precisionMetres"],
        message: `precisionMetres ${c.precisionMetres} does not match cellId ${c.cellId} (${derived} m)`,
      });
    }
    if (c.verifiedCount !== undefined && c.verifiedCount > c.recordCount) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["verifiedCount"], message: `verifiedCount ${c.verifiedCount} exceeds recordCount ${c.recordCount}` });
    }
  });

export const CellDistributionSchema = z.object({ cells: z.array(GridCellSchema) }).strict();

export const SummarySchema = z
  .object({
    totalRecords: z.number().int().nonnegative(),
    totalSpecies: z.number().int().nonnegative(),
    yearRange: z.object({ min: z.number().int(), max: z.number().int() }).strict(),
    recordsByYear: z.array(z.object({ year: z.number().int(), count: z.number().int() }).strict()),
    topGroups: z.array(z.object({ group: z.string(), count: z.number().int() }).strict()),
    coverageCaveat: z.string(),
  })
  .strict();

export const ProvenanceSchema = z
  .object({
    lastUpdated: z.string(),
    recordTotal: z.number().int().nonnegative(),
    sources: z.array(z.string()),
    coverageCaveats: z.array(z.string()),
    sensitivityPolicy: z
      .object({
        generalisationTiersMetres: z.array(z.number().int().positive()),
        appliesToProtectedTaxa: z.literal(true),
        note: z.string(),
      })
      .strict(),
    attributions: z.array(z.object({ label: z.string(), url: httpsUrl, licence: z.string() }).strict()),
  })
  .strict();

export type Health = z.infer<typeof HealthSchema>;
export type SpeciesListItem = z.infer<typeof SpeciesListItemSchema>;
export type SpeciesListPage = z.infer<typeof SpeciesListPageSchema>;
export type SpeciesDetail = z.infer<typeof SpeciesDetailSchema>;
export type SpeciesImage = z.infer<typeof SpeciesImageSchema>;
export type RecordRow = z.infer<typeof RecordRowSchema>;
export type RecordPage = z.infer<typeof RecordPageSchema>;
export type GridCell = z.infer<typeof GridCellSchema>;
export type CellDistribution = z.infer<typeof CellDistributionSchema>;
export type Summary = z.infer<typeof SummarySchema>;
export type Provenance = z.infer<typeof ProvenanceSchema>;
export type VerifiedStatus = RecordRow["verified"];
