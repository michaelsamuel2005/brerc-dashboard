// "What has been recorded near here" — the BAM-style radius query.
//
// The circle is the QUESTION, not the answer. It is drawn where the visitor put it, and
// what comes back is the set of already-generalised grid squares it touches. Nothing
// here refines a location: every square returned is the same square the map was already
// willing to draw, at the same published resolution. A circle drawn around the DATA
// would be a different and much worse thing — a circle has a centre, and a centre reads
// as "the record is here", which is precisely the claim generalisation exists to prevent.
//
// Consequence worth stating: a radius smaller than the squares cannot narrow anything.
// Ask for 100 m inside a 1 km square and you get that whole square, because that is all
// that is known. `radiusIsFinerThanData` lets the UI say so rather than implying the
// answer got sharper.

/** A ring of [lng, lat] positions, as produced by gridRefToPolygon.
 *  Typed as plain number arrays because that is what GeoJSON positions are: a tuple
 *  type here would force every caller to cast, and a cast is exactly the place a
 *  malformed position would slip through unchecked. Positions are validated below. */
export type Ring = readonly (readonly number[])[];

export interface RadiusCell {
  readonly cellId: string;
  readonly ring: Ring;
  readonly precisionMetres: number;
}

/** The minimum a value needs to be measured against a circle. */
type HasRing = { readonly ring: Ring };

/** Metres per degree of latitude. Constant enough over one English county. */
const METRES_PER_DEGREE_LAT = 111_320;

/**
 * Local metre offsets from a centre, using an equirectangular approximation.
 *
 * Over the West of England — roughly 40 km across, near 51.5°N — this is accurate to
 * well under a metre, which is four orders of magnitude finer than the 100 m floor any
 * published record has. A great-circle formula would be more correct and no more useful,
 * and this one is cheap enough to run over every cell on every pointer move.
 */
function toLocalMetres(
  point: readonly number[],
  centre: readonly [number, number],
): [number, number] | null {
  const [lng, lat] = point;
  // A position missing a coordinate is dropped rather than silently read as 0, which
  // would place it off the coast of Africa and inside every radius.
  if (typeof lng !== "number" || typeof lat !== "number") return null;
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  const latitudeScale = Math.cos((centre[1] * Math.PI) / 180);
  return [
    (lng - centre[0]) * METRES_PER_DEGREE_LAT * latitudeScale,
    (lat - centre[1]) * METRES_PER_DEGREE_LAT,
  ];
}

/**
 * Shortest distance in metres from a centre to a grid square, or 0 if the centre is
 * inside it.
 *
 * Grid squares are axis-aligned rectangles in lon/lat, so the bounding box IS the
 * square; there is no approximation in treating it as one.
 */
export function distanceToCellMetres(
  cell: HasRing,
  centre: readonly [number, number],
): number | null {
  if (cell.ring.length === 0) return null;
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const position of cell.ring) {
    const local = toLocalMetres(position, centre);
    if (local === null) continue;
    const [x, y] = local;
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null;
  // Distance from the origin (the centre, in local coordinates) to the rectangle.
  const dx = Math.max(minX, 0, -maxX);
  const dy = Math.max(minY, 0, -maxY);
  return Math.hypot(dx, dy);
}

/**
 * The cells a circle touches, nearest first.
 *
 * "Touches" and not "is contained by": a square that overlaps the circle at all holds
 * records that may be within it, and excluding it would tell the visitor there is
 * nothing there when we do not know that.
 */
export function cellsWithinRadius<T extends HasRing>(
  cells: readonly T[],
  centre: readonly [number, number],
  radiusMetres: number,
): (T & { distanceMetres: number })[] {
  if (!(radiusMetres > 0)) return [];
  const hits: (T & { distanceMetres: number })[] = [];
  for (const cell of cells) {
    const distance = distanceToCellMetres(cell, centre);
    if (distance !== null && distance <= radiusMetres) {
      hits.push({ ...cell, distanceMetres: distance });
    }
  }
  return hits.sort((a, b) => a.distanceMetres - b.distanceMetres);
}

/**
 * True when the requested radius is finer than the data it is filtering, so the UI can
 * say the answer is not as precise as the question.
 */
export function radiusIsFinerThanData(
  radiusMetres: number,
  cells: readonly { readonly precisionMetres: number }[],
): boolean {
  if (cells.length === 0) return false;
  const coarsest = Math.max(...cells.map((cell) => cell.precisionMetres));
  return radiusMetres < coarsest;
}

/** A closed ring approximating a circle, for drawing the query area on the map. */
export function circleRing(
  centre: readonly [number, number],
  radiusMetres: number,
  steps = 64,
): [number, number][] {
  const latitudeScale = Math.cos((centre[1] * Math.PI) / 180) || 1;
  const ring: [number, number][] = [];
  for (let i = 0; i <= steps; i += 1) {
    const angle = (i / steps) * 2 * Math.PI;
    const dx = (radiusMetres * Math.cos(angle)) / (METRES_PER_DEGREE_LAT * latitudeScale);
    const dy = (radiusMetres * Math.sin(angle)) / METRES_PER_DEGREE_LAT;
    ring.push([centre[0] + dx, centre[1] + dy]);
  }
  return ring;
}
