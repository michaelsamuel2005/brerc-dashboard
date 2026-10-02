import type { Finding, Severity } from './findings';

/**
 * Reviewer-attested manual-resolution ledger.
 *
 * WHY THIS EXISTS. Findings that need human judgement are real, so the pipeline must let a
 * NAMED reviewer record a decision it can verify. The fingerprint detects stale evidence;
 * it is not a cryptographic signature and the file still relies on repository review.
 *
 * THREE SAFETY PROPERTIES, each added after a runtime reproduction showed the previous
 * design could be subverted:
 *
 *  1. A deterministic WCAG non-conformance CANNOT be dismissed. Only findings whose
 *     severity is 'needs-human-decision' are dismissible; a measured 16x16 control that
 *     fails SC 2.5.8 must be fixed, or the finding must change because the code changed.
 *  2. `outcome` is validated at RUNTIME against the enum. A hand-edited JSON value such as
 *     "waived" is an invalid entry, not a silent dismissal.
 *  3. Resolutions are scoped to the complete evidence run. Browser engines and camera
 *     positions can change geometry at the same viewport, so project, camera and data mode
 *     are part of identity as well as viewport and state.
 */

export type ResolutionOutcome =
  /** Reviewer determined this is not a defect. Only valid for 'needs-human-decision'. */
  | 'dismissed'
  /** Reviewer confirmed this IS a defect. Keeps blocking until the code is fixed. */
  | 'confirmed';

const OUTCOMES: readonly string[] = ['dismissed', 'confirmed'];
const DISMISSIBLE: readonly Severity[] = ['needs-human-decision'];

export interface ResolutionScope {
  /** Playwright project/engine label, e.g. "a11y-webkit-V3-390x844". */
  readonly project: string;
  /** e.g. "320x640". */
  readonly viewport: string;
  /** e.g. "cell-selected". */
  readonly state: string;
  /** Stable camera schedule label, e.g. "initial-z12" or "not-applicable". */
  readonly camera: string;
  /** Distinguishes deterministic fixtures from a separately approved live-API run. */
  readonly dataMode: 'msw-mock' | 'live-api';
}

export interface Resolution {
  readonly findingId: string;
  readonly fingerprint: string;
  readonly outcome: ResolutionOutcome;
  readonly reviewer: string;
  readonly date: string;
  readonly justification: string;
  readonly scope: ResolutionScope;
}

export type LedgerProblem =
  | 'missing-finding-id'
  | 'missing-fingerprint'
  | 'missing-reviewer'
  | 'missing-justification'
  | 'justification-too-short'
  | 'invalid-date'
  | 'invalid-outcome'
  | 'missing-scope'
  | 'unknown-finding'
  | 'duplicate-resolution'
  | 'severity-not-dismissible'
  | 'unknown-scope-value';

export interface InvalidResolution {
  readonly resolution: unknown;
  readonly problems: readonly LedgerProblem[];
}

export interface LedgerApplication {
  readonly scope: ResolutionScope;
  readonly resolved: readonly Finding[];
  readonly unresolved: readonly Finding[];
  readonly stale: readonly { finding: Finding; resolution: Resolution }[];
  readonly confirmedDefects: readonly { finding: Finding; resolution: Resolution }[];
  readonly invalid: readonly InvalidResolution[];
  /**
   * True when every finding in this scope carries a valid, current, dismissing resolution.
   * NOT a conformance verdict — it says the ledger is clear, nothing about the other gates.
   */
  readonly ledgerResolved: boolean;
  readonly summary: Readonly<Record<string, number>>;
}

export interface ResolutionScopeVocabulary {
  readonly projects: readonly string[];
  readonly viewports: readonly string[];
  readonly states: readonly string[];
  readonly cameras: readonly string[];
  readonly dataModes: readonly ResolutionScope['dataMode'][];
  /** Optional exact matrix; when supplied, valid values in an invalid combination fail. */
  readonly scopes?: readonly ResolutionScope[];
}

export class ResolutionLedgerError extends Error {
  readonly problems: readonly string[];

  constructor(problems: readonly string[]) {
    super(`Invalid accessibility resolution ledger:\n${problems.join('\n')}`);
    this.name = 'ResolutionLedgerError';
    this.problems = problems;
  }
}

const MIN_JUSTIFICATION = 20;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z)?$/;

const sameScope = (a: ResolutionScope, b: ResolutionScope): boolean =>
  a.project === b.project &&
  a.viewport === b.viewport &&
  a.state === b.state &&
  a.camera === b.camera &&
  a.dataMode === b.dataMode;

const nonEmpty = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;

function isRealIsoDate(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const match = ISO_DATE.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day &&
    !Number.isNaN(Date.parse(value));
}

function scopeOf(value: unknown): ResolutionScope | null {
  if (value === null || typeof value !== 'object') return null;
  const scope = value as Partial<Record<keyof ResolutionScope, unknown>>;
  if (!nonEmpty(scope.project) || !nonEmpty(scope.viewport) ||
      !nonEmpty(scope.state) || !nonEmpty(scope.camera) ||
      (scope.dataMode !== 'msw-mock' && scope.dataMode !== 'live-api')) {
    return null;
  }
  return {
    project: scope.project,
    viewport: scope.viewport,
    state: scope.state,
    camera: scope.camera,
    dataMode: scope.dataMode
  };
}

export function validateResolution(
  raw: unknown, findingsById: ReadonlyMap<string, Finding>, scope: ResolutionScope
): LedgerProblem[] {
  const r = (raw !== null && typeof raw === 'object')
    ? raw as Partial<Resolution>
    : {};
  const problems: LedgerProblem[] = [];
  if (!nonEmpty(r.findingId)) problems.push('missing-finding-id');
  if (!nonEmpty(r.fingerprint)) problems.push('missing-fingerprint');
  if (!nonEmpty(r.reviewer)) problems.push('missing-reviewer');
  if (typeof r.justification !== 'string' || r.justification.trim().length === 0) {
    problems.push('missing-justification');
  } else if (r.justification.trim().length < MIN_JUSTIFICATION) {
    problems.push('justification-too-short');
  }
  if (!isRealIsoDate(r.date)) problems.push('invalid-date');
  // Runtime enum check: hand-edited JSON is data, not a type.
  if (!OUTCOMES.includes(r.outcome as string)) problems.push('invalid-outcome');
  const candidateScope = scopeOf(r.scope);
  if (!candidateScope) {
    problems.push('missing-scope');
    return problems;
  }
  if (!sameScope(candidateScope, scope)) return problems;

  const finding = typeof r.findingId === 'string' ? findingsById.get(r.findingId) : undefined;
  if (!finding) { problems.push('unknown-finding'); return problems; }
  if (r.outcome === 'dismissed' && !DISMISSIBLE.includes(finding.severity)) {
    problems.push('severity-not-dismissible');
  }
  return problems;
}

/**
 * Runtime boundary for the hand-edited JSON file. TypeScript types do not validate JSON.
 * The complete file is checked once so malformed entries in another scope cannot hide.
 */
export function parseResolutionLedger(
  raw: unknown,
  vocabulary?: ResolutionScopeVocabulary
): Resolution[] {
  if (raw === null || typeof raw !== 'object' ||
      !Array.isArray((raw as { resolutions?: unknown }).resolutions)) {
    throw new ResolutionLedgerError(['root.resolutions must be an array']);
  }

  const entries = (raw as { resolutions: unknown[] }).resolutions;
  const errors: string[] = [];
  const output: Resolution[] = [];
  const emptyFindings = new Map<string, Finding>();
  const seen = new Set<string>();

  entries.forEach((entry, index) => {
    const candidate = entry as Partial<Resolution>;
    const candidateScope = scopeOf(candidate?.scope);
    // Structural checks do not need a real run. Use the entry's own valid scope so the
    // semantic unknown-finding check is the only run-specific part we discard here.
    const validationScope = candidateScope ?? {
      project: '(invalid)', viewport: '(invalid)', state: '(invalid)',
      camera: '(invalid)', dataMode: 'msw-mock' as const
    };
    const problems = validateResolution(entry, emptyFindings, validationScope)
      .filter(problem => problem !== 'unknown-finding' && problem !== 'severity-not-dismissible');

    if (candidateScope && vocabulary) {
      const recognised = vocabulary.scopes
        ? vocabulary.scopes.some(scope => sameScope(scope, candidateScope))
        : vocabulary.projects.includes(candidateScope.project) &&
          vocabulary.viewports.includes(candidateScope.viewport) &&
          vocabulary.states.includes(candidateScope.state) &&
          vocabulary.cameras.includes(candidateScope.camera) &&
          vocabulary.dataModes.includes(candidateScope.dataMode);
      if (!recognised) problems.push('unknown-scope-value');
    }

    if (candidateScope && nonEmpty(candidate.findingId)) {
      const key = [
        candidateScope.project, candidateScope.viewport, candidateScope.state,
        candidateScope.camera, candidateScope.dataMode, candidate.findingId
      ].join('\u001f');
      if (seen.has(key)) problems.push('duplicate-resolution');
      seen.add(key);
    }

    if (problems.length > 0) {
      errors.push(`resolutions[${index}]: ${[...new Set(problems)].join(', ')}`);
    } else {
      output.push(entry as Resolution);
    }
  });

  if (errors.length > 0) throw new ResolutionLedgerError(errors);
  return output;
}

/**
 * Apply the ledger for ONE viewport+state. Entries scoped elsewhere are ignored, not
 * treated as errors — one file legitimately covers the whole matrix.
 */
export function applyLedger(
  findings: readonly Finding[], ledger: readonly Resolution[], scope: ResolutionScope
): LedgerApplication {
  const byId = new Map(findings.map(f => [f.id, f] as const));

  const inScope = ledger.filter(r => {
    const candidateScope = scopeOf(r?.scope);
    return candidateScope !== null && sameScope(candidateScope, scope);
  });
  const accepted = new Map<string, Resolution>();
  const invalid: InvalidResolution[] = [];

  for (const r of ledger) {
    const problems = validateResolution(r, byId, scope);
    const candidateScope = scopeOf(r?.scope);
    const isForThisScope = candidateScope !== null && sameScope(candidateScope, scope);
    if (!isForThisScope) {
      // Structural integrity is global: a typo-scope entry with an invalid outcome must
      // not disappear merely because this particular run does not select it.
      if (problems.length > 0) invalid.push({ resolution: r, problems });
      continue;
    }
    if (accepted.has(r.findingId)) problems.push('duplicate-resolution');
    if (problems.length > 0) { invalid.push({ resolution: r, problems }); continue; }
    accepted.set(r.findingId, r);
  }

  const resolved: Finding[] = [];
  const unresolved: Finding[] = [];
  const stale: { finding: Finding; resolution: Resolution }[] = [];
  const confirmedDefects: { finding: Finding; resolution: Resolution }[] = [];

  for (const f of findings) {
    const r = accepted.get(f.id);
    if (!r) { unresolved.push(f); continue; }
    if (r.fingerprint !== f.fingerprint) { stale.push({ finding: f, resolution: r }); continue; }
    if (r.outcome === 'confirmed') { confirmedDefects.push({ finding: f, resolution: r }); continue; }
    resolved.push(f);
  }

  return {
    scope, resolved, unresolved, stale, confirmedDefects, invalid,
    ledgerResolved:
      unresolved.length === 0 && stale.length === 0 &&
      confirmedDefects.length === 0 && invalid.length === 0,
    summary: {
      findings: findings.length,
      ledgerEntriesInScope: inScope.length,
      resolved: resolved.length,
      unresolved: unresolved.length,
      stale: stale.length,
      confirmedDefects: confirmedDefects.length,
      invalidLedgerEntries: invalid.length
    }
  };
}

export function describeBlockers(app: LedgerApplication): string[] {
  const where =
    `[${app.scope.project} / ${app.scope.viewport} / ${app.scope.state} / ` +
    `${app.scope.camera} / ${app.scope.dataMode}]`;
  const lines: string[] = [];
  for (const f of app.unresolved) {
    lines.push(`UNRESOLVED ${where} [${f.severity}] ${f.sc ? `SC ${f.sc} ` : ''}${f.detail}\n` +
               `           id=${f.id} fingerprint=${f.fingerprint}`);
  }
  for (const { finding, resolution } of app.stale) {
    lines.push(`STALE      ${where} ${finding.detail}\n` +
               `           signed by ${resolution.reviewer} against ${resolution.fingerprint}, now ${finding.fingerprint}`);
  }
  for (const { finding, resolution } of app.confirmedDefects) {
    lines.push(`DEFECT     ${where} ${finding.detail}\n` +
               `           confirmed by ${resolution.reviewer} on ${resolution.date} — fix required`);
  }
  for (const { resolution, problems } of app.invalid) {
    const findingId = resolution !== null && typeof resolution === 'object' &&
      typeof (resolution as { findingId?: unknown }).findingId === 'string'
      ? (resolution as { findingId: string }).findingId
      : '(missing finding id)';
    lines.push(`BAD LEDGER ${where} ${findingId}: ${problems.join(', ')}`);
  }
  return lines;
}
