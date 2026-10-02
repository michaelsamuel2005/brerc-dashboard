/**
 * Stable, dependency-free content fingerprints.
 *
 * Used to give every accessibility finding an identifier that (a) is the same across
 * runs for the same defect, so a reviewer's signed resolution keeps applying, and
 * (b) CHANGES when the underlying facts change, so a stale resolution is detected
 * rather than silently carried forward.
 *
 * FNV-1a rather than a crypto hash: this must run identically in Node and in the
 * browser with no imports, and it is a change-detector, not a security primitive.
 */

const FNV_OFFSET = 0x811c9dc5;
const FNV_PRIME = 0x01000193;

export function fnv1a(input: string): string {
  let h = FNV_OFFSET;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, FNV_PRIME) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

/** Deterministic JSON: keys sorted, so property order cannot change a fingerprint. */
export function stableStringify(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : `"${String(value)}"`;
  if (typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(',')}}`;
  }
  return '"<unserialisable>"';
}

export const fingerprintOf = (value: unknown): string => fnv1a(stableStringify(value));
