import {
  MANUAL_GATE_IDS,
  type ManualGateAttestation,
  type ManualGateId,
  type ManualGateResults
} from './evidence';

export class ManualGateFileError extends Error {
  readonly problems: readonly string[];

  constructor(problems: readonly string[]) {
    super(`Invalid accessibility manual-results file:\n${problems.join('\n')}`);
    this.name = 'ManualGateFileError';
    this.problems = problems;
  }
}

const nonEmpty = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;

const isGate = (value: unknown): value is ManualGateId =>
  typeof value === 'string' &&
  (MANUAL_GATE_IDS as readonly string[]).includes(value);

function validDate(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day;
}

/**
 * Parses the separately maintained manual-results file. Missing gates are valid data but
 * remain `not-assessed` in release evidence; malformed or duplicate attestations fail.
 */
export function parseManualGateFile(raw: unknown): ManualGateResults {
  if (raw === null || typeof raw !== 'object' ||
      !Array.isArray((raw as { attestations?: unknown }).attestations)) {
    throw new ManualGateFileError(['root.attestations must be an array']);
  }

  const output: Partial<Record<ManualGateId, ManualGateAttestation>> = {};
  const errors: string[] = [];

  (raw as { attestations: unknown[] }).attestations.forEach((entry, index) => {
    if (entry === null || typeof entry !== 'object') {
      errors.push(`attestations[${index}] must be an object`);
      return;
    }
    const value = entry as Record<string, unknown>;
    const gate = value['gate'];
    const outcome = value['outcome'];
    const problems: string[] = [];
    if (!isGate(gate)) problems.push('invalid-gate');
    if (outcome !== 'pass' && outcome !== 'fail' && outcome !== 'not-applicable') {
      problems.push('invalid-outcome');
    }
    if (!nonEmpty(value['reviewer'])) problems.push('missing-reviewer');
    if (!validDate(value['date'])) problems.push('invalid-date');
    if (!nonEmpty(value['environment'])) problems.push('missing-environment');
    if (!nonEmpty(value['evidence']) || value['evidence'].trim().length < 20) {
      problems.push('insufficient-evidence');
    }
    if (isGate(gate) && output[gate]) problems.push('duplicate-gate');

    if (problems.length > 0) {
      errors.push(`attestations[${index}]: ${problems.join(', ')}`);
      return;
    }

    if (isGate(gate) &&
        (outcome === 'pass' || outcome === 'fail' || outcome === 'not-applicable') &&
        nonEmpty(value['reviewer']) && validDate(value['date']) &&
        nonEmpty(value['environment']) && nonEmpty(value['evidence'])) {
      output[gate] = {
        outcome,
        reviewer: value['reviewer'],
        date: value['date'],
        environment: value['environment'],
        evidence: value['evidence']
      };
    }
  });

  if (errors.length > 0) throw new ManualGateFileError(errors);
  return output;
}
