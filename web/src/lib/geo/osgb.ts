// OSGB36 National Grid → WGS84, via the OS 7-parameter Helmert transform (sub-metre vs
// pyproj in the West of England — ample for 1 km cells). Deriving a cell's polygon from
// its VALIDATED grid ID means the server cannot mislabel a precise polygon as a coarse
// cell: the geometry always matches the ID. Verified against pyproj in osgb.test.ts.
const D2R = Math.PI / 180;
const S2R = Math.PI / (180 * 3600);
import { parseNumericGridRef } from "./gridref";

/** SW-corner easting/northing (EPSG:27700) + cell size (m) for an OS grid ref, or null. */
export function parseGridRef(ref: string): { easting: number; northing: number; size: number } | null {
  const parsed = parseNumericGridRef(ref);
  if (!parsed) return null;
  const { digits, e100, n100, size } = parsed;
  const half = digits.length / 2;
  const easting = e100 * 100000 + Number(digits.slice(0, half)) * size;
  const northing = n100 * 100000 + Number(digits.slice(half)) * size;
  return { easting, northing, size };
}

function enToOsgb36(E: number, N: number): [number, number] {
  const a = 6377563.396, b = 6356256.909, F0 = 0.9996012717;
  const lat0 = 49 * D2R, lon0 = -2 * D2R, N0 = -100000, E0 = 400000;
  const e2 = 1 - (b * b) / (a * a), n = (a - b) / (a + b), n2 = n * n, n3 = n2 * n;
  let lat = lat0, M = 0;
  do {
    lat = (N - N0 - M) / (a * F0) + lat;
    const Ma = (1 + n + 1.25 * n2 + 1.25 * n3) * (lat - lat0);
    const Mb = (3 * n + 3 * n2 + 2.625 * n3) * Math.sin(lat - lat0) * Math.cos(lat + lat0);
    const Mc = (1.875 * n2 + 1.875 * n3) * Math.sin(2 * (lat - lat0)) * Math.cos(2 * (lat + lat0));
    const Md = (35 / 24) * n3 * Math.sin(3 * (lat - lat0)) * Math.cos(3 * (lat + lat0));
    M = b * F0 * (Ma - Mb + Mc - Md);
  } while (Math.abs(N - N0 - M) >= 0.00001);
  const sL = Math.sin(lat), cL = Math.cos(lat), tL = Math.tan(lat);
  const nu = (a * F0) / Math.sqrt(1 - e2 * sL * sL);
  const rho = (a * F0 * (1 - e2)) / Math.pow(1 - e2 * sL * sL, 1.5);
  const eta2 = nu / rho - 1;
  const t2 = tL * tL, t4 = t2 * t2, t6 = t4 * t2, sec = 1 / cL, dE = E - E0;
  const VII = tL / (2 * rho * nu);
  const VIII = (tL / (24 * rho * nu ** 3)) * (5 + 3 * t2 + eta2 - 9 * t2 * eta2);
  const IX = (tL / (720 * rho * nu ** 5)) * (61 + 90 * t2 + 45 * t4);
  const X = sec / nu;
  const XI = (sec / (6 * nu ** 3)) * (nu / rho + 2 * t2);
  const XII = (sec / (120 * nu ** 5)) * (5 + 28 * t2 + 24 * t4);
  const XIIA = (sec / (5040 * nu ** 7)) * (61 + 662 * t2 + 1320 * t4 + 720 * t6);
  const latO = lat - VII * dE ** 2 + VIII * dE ** 4 - IX * dE ** 6;
  const lonO = lon0 + X * dE - XI * dE ** 3 + XII * dE ** 5 - XIIA * dE ** 7;
  return [latO, lonO];
}

function toCart(lat: number, lon: number, a: number, b: number): [number, number, number] {
  const e2 = 1 - (b * b) / (a * a), s = Math.sin(lat), c = Math.cos(lat);
  const nu = a / Math.sqrt(1 - e2 * s * s);
  return [nu * c * Math.cos(lon), nu * c * Math.sin(lon), (1 - e2) * nu * s];
}
function helmert(x: number, y: number, z: number): [number, number, number] {
  const tx = 446.448, ty = -125.157, tz = 542.06, s1 = 1 + -20.4894 / 1e6;
  const rx = 0.1502 * S2R, ry = 0.247 * S2R, rz = 0.8421 * S2R;
  return [tx + x * s1 - y * rz + z * ry, ty + x * rz + y * s1 - z * rx, tz - x * ry + y * rx + z * s1];
}
function toGeo(x: number, y: number, z: number, a: number, b: number): [number, number] {
  const e2 = 1 - (b * b) / (a * a), p = Math.sqrt(x * x + y * y);
  let lat = Math.atan2(z, p * (1 - e2)), prev = 0;
  do {
    prev = lat;
    const s = Math.sin(lat), nu = a / Math.sqrt(1 - e2 * s * s);
    lat = Math.atan2(z + e2 * nu * s, p);
  } while (Math.abs(lat - prev) > 1e-12);
  return [lat, Math.atan2(y, x)];
}

/** EPSG:27700 easting/northing → WGS84 [lng, lat]. */
export function enToWgs84(easting: number, northing: number): [number, number] {
  const [la, lo] = enToOsgb36(easting, northing);
  const [x, y, z] = toCart(la, lo, 6377563.396, 6356256.909);
  const [x2, y2, z2] = helmert(x, y, z);
  const [la2, lo2] = toGeo(x2, y2, z2, 6378137, 6356752.314245);
  return [lo2 / D2R, la2 / D2R];
}

/** Closed WGS84 ring for the square a grid ref denotes, or null if unparseable. */
export function gridRefToPolygon(ref: string): number[][] | null {
  const p = parseGridRef(ref);
  if (!p) return null;
  const { easting: e, northing: n, size: s } = p;
  const corners: [number, number][] = [[e, n], [e + s, n], [e + s, n + s], [e, n + s], [e, n]];
  return corners.map(([x, y]) => enToWgs84(x, y));
}

/** WGS84 [lng, lat] centroid of the square a grid ref denotes, or null. */
export function gridRefCentroid(ref: string): [number, number] | null {
  const p = parseGridRef(ref);
  if (!p) return null;
  return enToWgs84(p.easting + p.size / 2, p.northing + p.size / 2);
}
