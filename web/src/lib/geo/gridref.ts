// Display-only OS grid-reference helpers. NEVER used to fabricate/upsample precision;
// generalisation happens server-side (C2). Purely parses the precision a ref already has.
const PER_AXIS_METRES: Record<number, number> = { 1: 10000, 2: 1000, 3: 100, 4: 10, 5: 1 };

/** Resolution in metres implied by an OS grid ref, or null if unparseable. */
export function gridRefPrecisionMetres(ref: string): number | null {
  const cleaned = ref.replace(/\s+/g, "").toUpperCase();
  const match = /^[A-Z]{1,2}(\d+)$/.exec(cleaned);
  if (!match) return null;
  const digits = match[1];
  if (digits === undefined || digits.length % 2 !== 0) return null;
  const perAxis = digits.length / 2;
  return PER_AXIS_METRES[perAxis] ?? null;
}

/** Human label for a resolution in metres, e.g. 1000 -> "1 km square". */
export function precisionLabel(metres: number): string {
  if (metres >= 1000) return `${metres / 1000} km square`;
  return `${metres} m square`;
}
