import { describe, it, expect } from 'vitest';
import { makeFinding } from './findings';

const input = {
  kind: 'target-undersized' as const,
  severity: 'wcag-nonconformance' as const,
  sc: '2.5.8',
  detail: 'too small',
  evidence: { label: 'Zoom in', index: 3, width: 16, height: 16 }
};

describe('findings', () => {
  it('derives a stable id from the identity keys only', () => {
    const a = makeFinding(input, ['label', 'index']);
    const b = makeFinding({ ...input, evidence: { ...input.evidence, width: 17 } }, ['label', 'index']);
    expect(a.id).toBe(b.id);          // same defect, geometry drifted
  });
  it('changes the fingerprint when any evidence changes', () => {
    const a = makeFinding(input, ['label', 'index']);
    const b = makeFinding({ ...input, evidence: { ...input.evidence, width: 17 } }, ['label', 'index']);
    expect(a.fingerprint).not.toBe(b.fingerprint);
  });
  it('changes the id when an identity key changes', () => {
    const a = makeFinding(input, ['label', 'index']);
    const b = makeFinding({ ...input, evidence: { ...input.evidence, index: 4 } }, ['label', 'index']);
    expect(a.id).not.toBe(b.id);
  });
  it('prefixes the id with the kind so it is readable in CI output', () => {
    expect(makeFinding(input, ['label']).id.startsWith('target-undersized:')).toBe(true);
  });
  it('treats a missing identity key as null rather than throwing', () => {
    const f = makeFinding(input, ['label', 'nonexistent']);
    expect(f.id).toMatch(/^target-undersized:[0-9a-f]{8}$/);
  });
  it('preserves severity, sc and detail verbatim', () => {
    const f = makeFinding(input, ['label']);
    expect(f.severity).toBe('wcag-nonconformance');
    expect(f.sc).toBe('2.5.8');
    expect(f.detail).toBe('too small');
  });
});
