import { describe, expect, it } from 'vitest';
import { ManualGateFileError, parseManualGateFile } from './manualGates';

const valid = {
  gate: 'screenReader',
  outcome: 'pass',
  reviewer: 'Named accessibility reviewer',
  date: '2026-07-26',
  environment: 'iPhone 15, iOS 20, Safari, VoiceOver',
  evidence: 'Recorded transcript and issue checklist stored with the release evidence.'
};

describe('manual gate file runtime boundary', () => {
  it('accepts an empty file while leaving every release gate unassessed', () => {
    expect(parseManualGateFile({ attestations: [] })).toEqual({});
  });
  it('parses a complete attestation', () => {
    expect(parseManualGateFile({ attestations: [valid] }).screenReader?.outcome)
      .toBe('pass');
  });
  it('rejects malformed roots and entries', () => {
    expect(() => parseManualGateFile({})).toThrow(ManualGateFileError);
    expect(() => parseManualGateFile({ attestations: [null] }))
      .toThrow(ManualGateFileError);
  });
  it('rejects impossible dates and token evidence', () => {
    expect(() => parseManualGateFile({
      attestations: [{ ...valid, date: '2026-02-31', evidence: 'fine' }]
    })).toThrow(/invalid-date.*insufficient-evidence/);
  });
  it('rejects duplicate gates', () => {
    expect(() => parseManualGateFile({ attestations: [valid, valid] }))
      .toThrow(/duplicate-gate/);
  });
  it('rejects an unknown gate or outcome', () => {
    expect(() => parseManualGateFile({
      attestations: [{ ...valid, gate: 'looksGood', outcome: 'waived' }]
    })).toThrow(/invalid-gate.*invalid-outcome/);
  });
});
