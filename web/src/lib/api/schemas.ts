// ---------------------------------------------------------------------------
// Zod schemas = the SINGLE SOURCE OF TRUTH for the API contract (PLAN apiContract).
// Every schema is .strict(): any unexpected key (a leaked Recorder1 / BLISS /
// Eastings / Northings / Comments / sensitivity marker) makes the parse FAIL LOUDLY
// rather than flow into the UI. This is the client-side C2 net (server-side is the fix).
//
// It is also a RUNTIME safety gate, not just a shape check:
//   - a record's grid reference must resolve to EXACTLY its stated precisionMetres, and
//   - every public location must be at or coarser than the 100 m public floor, and
//   - URLs must be https (so javascript:/data: attribution links cannot parse).
// These run on every parsed response, including the real API — not only on fixtures.
// Public-safe domain types are inferred from these schemas so they cannot drift.
// ---------------------------------------------------------------------------
import { z } from "zod";
import { gridRefPrecisionMetres } from "../geo/gridref";

/** Coarsest allowed public resolution. Nothing finer may reach the client (C2 floor). */
export const PUBLIC_MIN_PRECISION_METRES = 100;

/** Normalise the raw `verified` string (handles the en-dash + variants) into an enum. */
export function normaliseVerified(raw: string): "accepted" | "unconfirmed" | "rejected" | "unknown" {
  const s = raw.toLowerCase();
  if (s.includes("accept")) return "accepted";
  if (s.includes("reject")) return "rejected";
  if (s.includes("unconfirm") || s.includes("pending") || s.includes("unverified")) return "unconfirmed";
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
  // Cross-field C2 gate: the grid reference must resolve to exactly its stated precision.
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

export const GridCellPropsSchema = z
  .object({
    cellId: z.string().min(1),
    precisionMetres: z.number().int().min(PUBLIC_MIN_PRECISION_METRES),
    recordCount: z.number().int().nonnegative(),
    verifiedCount: z.number().int().nonnegative().optional(),
  })
  .strict()
  .superRefine((p, ctx) => {
    if (p.verifiedCount !== undefined && p.verifiedCount > p.recordCount) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["verifiedCount"],
        message: `verifiedCount ${p.verifiedCount} exceeds recordCount ${p.recordCount}`,
      });
    }
  });

export const GridCellFeatureSchema = z
  .object({
    type: z.literal("Feature"),
    geometry: z
      .object({
        type: z.literal("Polygon"),
        coordinates: z.array(z.array(z.array(z.number()))),
      })
      .strict(),
    properties: GridCellPropsSchema,
  })
  .strict();

export const CellCollectionSchema = z
  .object({
    type: z.literal("FeatureCollection"),
    features: z.array(GridCellFeatureSchema),
  })
  .strict();

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
export type GridCellFeature = z.infer<typeof GridCellFeatureSchema>;
export type CellCollection = z.infer<typeof CellCollectionSchema>;
export type Summary = z.infer<typeof SummarySchema>;
export type Provenance = z.infer<typeof ProvenanceSchema>;
export type VerifiedStatus = RecordRow["verified"];
