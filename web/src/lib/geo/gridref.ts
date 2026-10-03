// Display-only OS grid-reference helpers. NEVER used to fabricate/upsample precision;
// generalisation happens server-side (C2). Purely parses the precision a ref already has.
const PER_AXIS_METRES: Record<number, number> = { 1: 10000, 2: 1000, 3: 100, 4: 10, 5: 1 };

export type ParsedNumericGridRef = {
  letters: string;
  digits: string;
  e100: number;
  n100: number;
  size: number;
};

/** Parse the one canonical public BNG form used by precision checks and geometry. */
export function parseNumericGridRef(ref: string): ParsedNumericGridRef | null {
  const cleaned = ref.replace(/\s+/g, "").toUpperCase();
  const match = /^([A-HJ-Z]{2})(\d{2,10})$/.exec(cleaned);
  if (!match) return null;
  const letters = match[1];
  const digits = match[2];
  if (letters === undefined || digits === undefined || digits.length % 2 !== 0) return null;

  let first = letters.charCodeAt(0) - 65;
  let second = letters.charCodeAt(1) - 65;
  if (first > 7) first -= 1; // I is omitted from OS lettering
  if (second > 7) second -= 1;
  const e100 = ((first - 2) % 5) * 5 + (second % 5);
  const n100 = 19 - Math.floor(first / 5) * 5 - Math.floor(second / 5);
  if (e100 < 0 || e100 > 6 || n100 < 0 || n100 > 12) return null;

  const size = PER_AXIS_METRES[digits.length / 2];
  if (size === undefined) return null;
  return { letters, digits, e100, n100, size };
}

/** Resolution in metres implied by an OS grid ref, or null if unparseable. */
export function gridRefPrecisionMetres(ref: string): number | null {
  return parseNumericGridRef(ref)?.size ?? null;
}

/** Human label for a resolution in metres, e.g. 1000 -> "1 km square". */
export function precisionLabel(metres: number): string {
  if (metres >= 1000) return `${metres / 1000} km square`;
  return `${metres} m square`;
}
