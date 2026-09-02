// ---------------------------------------------------------------------------
// Zod schemas = the SINGLE SOURCE OF TRUTH for the API contract (PLAN apiContract).
// Every schema is .strict(): any unexpected key (a leaked Recorder1 / BLISS / easting(s) /
// northing(s) / Comments / sensitive/sensitivity marker) makes the parse FAIL LOUDLY. This is the
// client-side C2 net (the approval-bound server policy is the safety boundary).
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

/** Normalise a raw `verified` verdict into an enum. Fail-safe on anything ambiguous.
 *
 *  ORDER IS LOAD-BEARING. The distinction a substring search gets wrong:
 *
 *    negating ACCEPTANCE   -> a rejection      ("not accepted", "unaccepted")
 *    negating VERIFICATION -> not yet done     ("not verified", "unconfirmed")
 *
 *  The previous implementation tested `s.includes("accept")` with no negation
 *  check before it, so "Not accepted" — which contains "accept" and no "reject" —
 *  was classified ACCEPTED. Measured against a 63-case corpus it produced 10 false
 *  accepts, each one showing a record a determiner actively turned down as
 *  verified, on a public map whose whole claim is that a verified record has been
 *  checked by somebody. It also returned "unknown" for 26 legible verdicts
 *  ("Verified", "Confirmed", "Provisional", "Awaiting verification", "Refused").
 *
 *  Kept in EXACT parity with `normalise_verified` in api/etl/contract.py. The two
 *  are asserted against a shared corpus; if you change one, change both.
 */
export function normaliseVerified(raw: string): "accepted" | "unconfirmed" | "rejected" | "unknown" {
  // z.string() guarantees a string inside the schema, but this function is
  // exported and a malformed response should degrade, not throw.
  if (typeof raw !== "string") return "unknown";
  const s = raw.trim();
  if (s === "") return "unknown";

  // 1. An active negative determination.
  if (/\b(?:reject\w*|refus\w*|declin\w*|incorrect|invalid|erroneous)\b/i.test(s)) return "rejected";
  // 2. Verification not completed. BEFORE the negated-acceptance test, so that
  //    "unconfirmed" and "not verified" are not misread as rejections.
  if (
    /\b(?:unconfirm\w*|unverif\w*|provisional|uncertain|pending|await\w*|(?:not|never|un)[\s-]*(?:been[\s-]+)?(?:verif\w*|confirm\w*|check\w*)|needs?[\s-]+(?:verification|confirmation|checking|approval)|to[\s-]+be[\s-]+(?:verified|confirmed|checked))\b/i.test(s)
  ) {
    return "unconfirmed";
  }
  // 3. A negated acceptance. Only reached once the unconfirmed patterns missed.
  if (/\b(?:not|non|never|un|dis)[\s-]*(?:been[\s-]+)?accept\w*/i.test(s)) return "rejected";
  // 4. A positive determination — the ONLY path to "accepted".
  if (/\b(?:accept\w*|verified|confirmed|correct|valid|determined)\b/i.test(s)) return "accepted";
  // 5. Anything unrecognised. Real BRERC data contains values such as "BRERC (1)";
  //    an unreadable verdict must never inflate a verified count.
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

const displayText = z.string().trim().min(1);
const speciesSlug = z.string().trim().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Invalid species slug");

/** Identity attached to every response backed by an atomic publication release. */
export const ReleaseIdentitySchema = z
  .object({
    releaseId: z.string().uuid(),
    datasetVersion: displayText,
  })
  .strict();

const releaseIdentityFields = ReleaseIdentitySchema.shape;

export const SpeciesSortSchema = z.enum([
  "name-asc",
  "scientific-name-asc",
  "records-desc",
  "latest-record-desc",
]);

export const SpeciesGroupFacetSchema = z
  .object({
    value: displayText,
    label: displayText,
    speciesCount: z.number().int().nonnegative(),
  })
  .strict();

export const SpeciesListItemSchema = z
  .object({
    speciesId: displayText,
    slug: speciesSlug,
    scientificName: displayText,
    commonName: displayText.nullable(),
    /** Null when the release publishes no taxonomic grouping for this species.
     *
     *  Two cases produce it, and both must stay visible rather than be hidden
     *  or relabelled: a release that publishes no grouping at all (the source's
     *  taxon field is free text and is not published without a reviewed
     *  vocabulary), and a species whose source value falls outside that
     *  vocabulary once one exists. A placeholder string would be a taxonomic
     *  claim the release does not support. */
    group: displayText.nullable(),
    recordCount: z.number().int().nonnegative(),
    firstYear: z.number().int().nullable(),
    lastYear: z.number().int().nullable(),
    hasImage: z.boolean(),
  })
  .strict()
  .superRefine((species, ctx) => {
    const hasYears = species.firstYear !== null && species.lastYear !== null;
    if ((species.recordCount === 0) !== !hasYears) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["firstYear"],
        message: "zero-record species must have no year range; recorded species must have both years",
      });
    }
    if (species.firstYear !== null && species.lastYear !== null && species.firstYear > species.lastYear) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["lastYear"], message: "lastYear precedes firstYear" });
    }
  });

export const SpeciesListPageSchema = z
  .object({
    ...releaseIdentityFields,
    items: z.array(SpeciesListItemSchema),
    page: z.number().int().positive(),
    pageSize: z.number().int().positive(),
    total: z.number().int().nonnegative(),
    facets: z
      .object({
        groups: z.array(SpeciesGroupFacetSchema),
      })
      .strict(),
  })
  .strict()
  .superRefine((result, ctx) => {
    if (result.items.length > result.pageSize) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["items"], message: "page contains more items than pageSize" });
    }
    if (result.items.length > result.total) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["total"], message: "total is smaller than this page" });
    }
    const facetValues = new Set(result.facets.groups.map((group) => group.value));
    if (facetValues.size !== result.facets.groups.length) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["facets", "groups"], message: "group facets must be unique" });
    }
    for (const [index, species] of result.items.entries()) {
      // An ungrouped species is legitimate and has no facet to belong to. A
      // group that IS published still must appear in the authoritative facet
      // list, so the filter can never omit a value the results contain.
      if (species.group !== null && !facetValues.has(species.group)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["items", index, "group"],
          message: "species group is missing from the authoritative facets",
        });
      }
    }
    const speciesIds = new Set(result.items.map((species) => species.speciesId));
    if (speciesIds.size !== result.items.length) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["items"], message: "species IDs must be unique within a page" });
    }
    const slugs = new Set(result.items.map((species) => species.slug));
    if (slugs.size !== result.items.length) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["items"], message: "species slugs must be unique within a page" });
    }
  });

export const SpeciesImageSchema = z
  .object({
    url: httpsUrl,
    attributionText: displayText,
    licence: displayText,
    licenceUrl: httpsUrl,
    sourceUrl: httpsUrl,
    approvalReference: displayText,
    alt: displayText,
  })
  .strict();

export const DescriptionSourceSchema = z
  .object({
    label: displayText,
    sourceUrl: httpsUrl.optional(),
    licence: displayText.optional(),
    licenceUrl: httpsUrl.optional(),
    approvalReference: displayText,
  })
  .strict()
  .superRefine((source, ctx) => {
    if (source.licenceUrl !== undefined && source.licence === undefined) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["licence"],
        message: "licence text is required when a licence URL is supplied",
      });
    }
  });

export const SpeciesDetailSchema = z
  .object({
    ...releaseIdentityFields,
    speciesId: displayText,
    slug: speciesSlug,
    scientificName: displayText,
    commonName: displayText.nullable(),
    /** Null when ungrouped — see SpeciesListItemSchema.group. */
    group: displayText.nullable(),
    description: displayText.optional(),
    descriptionSource: DescriptionSourceSchema.optional(),
    imagePublication: z.enum(["fallback-only", "approved-assets"]),
    image: SpeciesImageSchema.optional(),
    stats: z
      .object({
        recordCount: z.number().int().nonnegative(),
        yearRange: z.tuple([z.number().int(), z.number().int()]).nullable(),
        verificationAvailable: z.boolean(),
        verifiedCount: z.number().int().nonnegative().nullable(),
      })
      .strict(),
  })
  .strict()
  .superRefine((species, ctx) => {
    if ((species.description !== undefined) !== (species.descriptionSource !== undefined)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: species.description === undefined ? ["description"] : ["descriptionSource"],
        message: "description and descriptionSource must be published together",
      });
    }
    if (species.imagePublication === "fallback-only" && species.image !== undefined) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["image"],
        message: "fallback-only publication cannot expose a species image",
      });
    }
    if (species.imagePublication === "approved-assets" && species.image === undefined) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["image"],
        message: "approved-assets publication requires an approved image",
      });
    }
    if (species.stats.verificationAvailable !== (species.stats.verifiedCount !== null)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["stats", "verifiedCount"],
        message: "verifiedCount must be null exactly when verification is unavailable",
      });
    }
    if (
      species.stats.verifiedCount !== null &&
      species.stats.verifiedCount > species.stats.recordCount
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["stats", "verifiedCount"],
        message: "verifiedCount exceeds recordCount",
      });
    }
    const range = species.stats.yearRange;
    if ((species.stats.recordCount === 0) !== (range === null)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["stats", "yearRange"],
        message: "yearRange must be null exactly when there are no records",
      });
    }
    if (range && range[0] > range[1]) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["stats", "yearRange"],
        message: "yearRange starts after it ends",
      });
    }
  });

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
    verified: z.string().transform(normaliseVerified).optional(),
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

export const RecordPublicationSchema = z
  .object({
    mode: z.enum(["aggregates-only", "individual-records"]),
    fields: z
      .object({
        abundance: z.boolean(),
        place: z.boolean(),
        recordType: z.boolean(),
        verification: z.boolean(),
      })
      .strict(),
  })
  .strict();

export const RecordPageSchema = z
  .object({
    ...releaseIdentityFields,
    publication: RecordPublicationSchema,
    items: z.array(RecordRowSchema),
    page: z.number().int().positive(),
    pageSize: z.number().int().positive(),
    total: z.number().int().nonnegative(),
  })
  .strict()
  .superRefine((result, ctx) => {
    if (result.items.length > result.pageSize) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["items"],
        message: "record page contains more items than pageSize",
      });
    }
    if (result.items.length > result.total) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["total"],
        message: "record total is smaller than this page",
      });
    }

    const { mode, fields } = result.publication;
    if (mode === "aggregates-only") {
      if (result.items.length !== 0 || result.total !== 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["publication", "mode"],
          message: "aggregates-only responses cannot expose individual record rows",
        });
      }
      if (fields.abundance || fields.place || fields.recordType || fields.verification) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["publication", "fields"],
          message: "aggregates-only responses cannot advertise individual-record fields",
        });
      }
    }

    result.items.forEach((row, index) => {
      const fieldRules = [
        ["abundance", fields.abundance, "abundance is not published"],
        ["place", fields.place, "place is not published"],
        ["recordType", fields.recordType, "recordType is not published"],
        ["verified", fields.verification, "verification is unavailable"],
      ] as const;

      for (const [field, enabled, disabledMessage] of fieldRules) {
        const hasValue = row[field] !== undefined && row[field] !== null;
        if (!enabled && hasValue) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["items", index, field],
            message: disabledMessage,
          });
        }
        if (enabled && !Object.prototype.hasOwnProperty.call(row, field)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["items", index, field],
            message: `${field} is required when its publication capability is enabled`,
          });
        }
      }
    });
  });

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

export const CellDistributionSchema = z
  .object({
    ...releaseIdentityFields,
    verificationAvailable: z.boolean(),
    cells: z.array(GridCellSchema),
  })
  .strict()
  .superRefine((distribution, ctx) => {
    distribution.cells.forEach((cell, index) => {
      const hasVerifiedCount = Object.prototype.hasOwnProperty.call(cell, "verifiedCount");
      if (distribution.verificationAvailable !== hasVerifiedCount) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["cells", index, "verifiedCount"],
          message: distribution.verificationAvailable
            ? "verifiedCount is required when verification is available"
            : "verifiedCount must be omitted when verification is unavailable",
        });
      }
    });
  });

/**
 * The largest pageSize the API will accept (`MAX_PAGE_SIZE` in api/app/config.py).
 *
 * Exported so the MSW mock enforces the SAME limit as the service. It did not: the mock
 * rejected anything over 50 while the API allows 100, so a page asking for 100 worked
 * against the real backend and returned 400 against the mock. Nothing caught it because
 * nothing had asked for more than 20. One constant, both sides.
 */
export const MAX_PAGE_SIZE = 100;

export const SummarySchema = z
  .object({
    ...releaseIdentityFields,
    totalRecords: z.number().int().nonnegative(),
    totalSpecies: z.number().int().nonnegative(),
    yearRange: z.object({ min: z.number().int(), max: z.number().int() }).strict().nullable(),
    recordsByYear: z.array(z.object({ year: z.number().int(), count: z.number().int().positive() }).strict()),
    topGroups: z.array(z.object({ group: displayText, count: z.number().int().nonnegative() }).strict()),
    coverageCaveat: displayText,
  })
  .strict()
  .superRefine((summary, ctx) => {
    const range = summary.yearRange;
    if ((summary.totalRecords === 0) !== (range === null)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["yearRange"],
        message: "yearRange must be null exactly when there are no records",
      });
    }
    if (range && range.min > range.max) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["yearRange"], message: "yearRange starts after it ends" });
    }
    const yearTotal = summary.recordsByYear.reduce((total, entry) => total + entry.count, 0);
    if (yearTotal !== summary.totalRecords) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["recordsByYear"],
        message: "year totals do not reconcile with totalRecords",
      });
    }
    for (let index = 0; index < summary.recordsByYear.length; index += 1) {
      const entry = summary.recordsByYear[index];
      const previous = summary.recordsByYear[index - 1];
      if (previous && entry && entry.year <= previous.year) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["recordsByYear", index, "year"],
          message: "years must be unique and strictly ascending",
        });
      }
      if (range && entry && (entry.year < range.min || entry.year > range.max)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["recordsByYear", index, "year"],
          message: "year lies outside yearRange",
        });
      }
    }
    if (range && summary.recordsByYear.length > 0) {
      const first = summary.recordsByYear[0]?.year;
      const last = summary.recordsByYear[summary.recordsByYear.length - 1]?.year;
      if (first !== range.min || last !== range.max) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["yearRange"],
          message: "yearRange must match the first and last years carrying records",
        });
      }
    }
  });

export const ProvenanceSchema = z
  .object({
    ...releaseIdentityFields,
    lastUpdated: z.string(),
    recordTotal: z.number().int().nonnegative(),
    sources: z.array(z.string()),
    coverageCaveats: z.array(z.string()),
    sensitivityPolicy: z
      .object({
        protectedRecordsMode: z.enum(["generalised", "withheld"]),
        publishedLocationTiersMetres: z
          .array(z.union([z.literal(100), z.literal(1_000), z.literal(10_000)]))
          .refine(
            (tiers) => tiers.every((tier, index) => index === 0 || tier > tiers[index - 1]!),
            "published location tiers must be unique and strictly ascending",
          ),
        note: z.string().min(1),
      })
      .strict(),
    attributions: z.array(z.object({ label: z.string(), url: httpsUrl, licence: z.string() }).strict()),
  })
  .strict();

export type Health = z.infer<typeof HealthSchema>;
export type ReleaseIdentity = z.infer<typeof ReleaseIdentitySchema>;
export type SpeciesSort = z.infer<typeof SpeciesSortSchema>;
export type SpeciesGroupFacet = z.infer<typeof SpeciesGroupFacetSchema>;
export type SpeciesListItem = z.infer<typeof SpeciesListItemSchema>;
export type SpeciesListPage = z.infer<typeof SpeciesListPageSchema>;
export type SpeciesDetail = z.infer<typeof SpeciesDetailSchema>;
export type SpeciesImage = z.infer<typeof SpeciesImageSchema>;
export type DescriptionSource = z.infer<typeof DescriptionSourceSchema>;
export type RecordRow = z.infer<typeof RecordRowSchema>;
export type RecordPublication = z.infer<typeof RecordPublicationSchema>;
export type RecordPage = z.infer<typeof RecordPageSchema>;
export type GridCell = z.infer<typeof GridCellSchema>;
export type CellDistribution = z.infer<typeof CellDistributionSchema>;
export type Summary = z.infer<typeof SummarySchema>;
export type Provenance = z.infer<typeof ProvenanceSchema>;
export type VerifiedStatus = RecordRow["verified"];
