import { fingerprintOf } from './fingerprint';

/**
 * A single thing a human may need to look at.
 *
 * Everything the automated passes produce is a Finding. Nothing is a verdict until a
 * named reviewer resolves it in the ledger (see resolutionLedger.ts). This is what
 * makes the conformance gate reachable: previously every map result and every valid
 * exception claim blocked the report unconditionally, so the gate could never go green.
 */

export type FindingKind =
  | 'target-undersized'
  | 'target-manual-review'
  | 'target-overlap'
  | 'target-overlap-same-action-claimed'
  | 'target-invalid-geometry'
  | 'target-invalid-claim'
  | 'target-exception-claimed'
  | 'collector-duplicate-index'
  | 'project-rule-shortfall'
  | 'project-rule-manual-review'
  | 'map-cell-below-threshold'
  | 'map-cell-manual-review'
  | 'map-cell-not-rendered'
  | 'map-rendered-not-in-canonical'
  | 'map-collection-skipped'
  | 'map-inconclusive'
  | 'map-error';

export type Severity =
  | 'wcag-nonconformance'
  | 'project-requirement'
  | 'needs-human-decision'
  | 'data-quality';

export interface Finding {
  /** Stable across runs for the same defect; changes when the facts change. */
  id: string;
  /** Fingerprint of the evidence. A resolution signed against a different one is stale. */
  fingerprint: string;
  kind: FindingKind;
  severity: Severity;
  /** Success criterion, where one applies. */
  sc: string | null;
  detail: string;
  evidence: Readonly<Record<string, string | number | boolean | null>>;
}

export interface FindingInput {
  kind: FindingKind;
  severity: Severity;
  sc: string | null;
  detail: string;
  evidence: Readonly<Record<string, string | number | boolean | null>>;
}

/**
 * Identity uses kind + a caller-chosen stable subset of the evidence (passed as
 * `identityKeys`), so that a finding keeps its id when incidental numbers move by a
 * fraction of a pixel, while the fingerprint still records the exact evidence.
 */
export function makeFinding(input: FindingInput, identityKeys: readonly string[]): Finding {
  const identity: Record<string, string | number | boolean | null> = {};
  for (const key of identityKeys) {
    const v = input.evidence[key];
    identity[key] = v === undefined ? null : v;
  }
  return {
    id: `${input.kind}:${fingerprintOf(identity)}`,
    fingerprint: fingerprintOf({ kind: input.kind, evidence: input.evidence }),
    kind: input.kind,
    severity: input.severity,
    sc: input.sc,
    detail: input.detail,
    evidence: input.evidence
  };
}
