import { describe, it, expect } from 'vitest';
import { fnv1a, stableStringify, fingerprintOf } from './fingerprint';

describe('fingerprint', () => {
  it('is stable for the same input', () => {
    expect(fnv1a('hello')).toBe(fnv1a('hello'));
  });
  it('differs for different input', () => {
    expect(fnv1a('hello')).not.toBe(fnv1a('hellp'));
  });
  it('always produces 8 hex characters', () => {
    for (const s of ['', 'a', 'a much longer string with spaces', '£€✓']) {
      expect(fnv1a(s)).toMatch(/^[0-9a-f]{8}$/);
    }
  });
  it('is insensitive to object key order', () => {
    expect(fingerprintOf({ a: 1, b: 2 })).toBe(fingerprintOf({ b: 2, a: 1 }));
  });
  it('is sensitive to values', () => {
    expect(fingerprintOf({ a: 1 })).not.toBe(fingerprintOf({ a: 2 }));
  });
  it('distinguishes nested structures', () => {
    expect(fingerprintOf({ a: { b: 1 } })).not.toBe(fingerprintOf({ a: { b: 2 } }));
  });
  it('is sensitive to array order', () => {
    expect(fingerprintOf([1, 2])).not.toBe(fingerprintOf([2, 1]));
  });
  it('serialises null, booleans and strings distinctly', () => {
    expect(stableStringify(null)).toBe('null');
    expect(stableStringify(true)).toBe('true');
    expect(stableStringify('true')).toBe('"true"');
  });
  it('encodes non-finite numbers as strings rather than JSON null', () => {
    expect(stableStringify(NaN)).toBe('"NaN"');
    expect(stableStringify(Infinity)).toBe('"Infinity"');
    expect(stableStringify(NaN)).not.toBe(stableStringify(null));
  });
  it('drops undefined properties so they cannot shift a fingerprint', () => {
    expect(fingerprintOf({ a: 1, b: undefined })).toBe(fingerprintOf({ a: 1 }));
  });
});
