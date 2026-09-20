import { describe, expect, it } from 'vitest';
import { ManualGateFileError, parseManualGateFile } from './manualGates';

const valid = {
  gate: 'screenReader',
  outcome: 'pass',
  reviewer: 'Named accessibility reviewer',
  date: '2026-07-26',
  environment: 'iPhone 15, iOS 20, Safari, VoiceOver',
  evidence: 'Recorded transcript and issue checklist stored with the release evidence.',
  commitSha: '2700a904178f707b6439ab1935d06d82eb2928cc',
  releaseManifestSha256: `sha256:${'a'.repeat(64)}`,
  deployedUrl: 'https://dashboard.brerc.org.uk/'
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
  it('rejects not-applicable because every release gate requires observation', () => {
    expect(() => parseManualGateFile({
      attestations: [{ ...valid, outcome: 'not-applicable' }]
    })).toThrow(/invalid-outcome/);
  });
  it('binds each attestation to an exact commit, release manifest and HTTPS URL', () => {
    expect(() => parseManualGateFile({
      attestations: [{
        ...valid,
        commitSha: 'short',
        releaseManifestSha256: 'sha256:placeholder',
        deployedUrl: 'http://localhost:4173/'
      }]
    })).toThrow(
      /invalid-commit-sha.*invalid-release-manifest-sha256.*invalid-deployed-url/
    );
  });
  it('rejects deployed URLs containing credentials or fragments', () => {
    for (const deployedUrl of [
      'https://reviewer:secret@dashboard.brerc.org.uk/',
      'https://dashboard.brerc.org.uk/#internal-state'
    ]) {
      expect(() => parseManualGateFile({
        attestations: [{ ...valid, deployedUrl }]
      })).toThrow(/invalid-deployed-url/);
    }
  });
});
