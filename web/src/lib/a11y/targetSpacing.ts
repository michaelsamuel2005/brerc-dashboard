import { makeFinding, type Finding } from './findings';

/**
 * WCAG 2.2 SC 2.5.8 Target Size (Minimum) — geometry and classification.
 *
 * RUNS IN NODE, NOT IN THE BROWSER. Playwright serialises a function into the page
 * without its module scope, so a helper referencing a module constant throws
 * "ReferenceError: AA_MIN is not defined" (verified against real Chromium). The browser
 * side only COLLECTS plain rectangles (collectTargets.ts); judgement happens here,
 * where it is unit-tested.
 *
 * For a non-developer maintainer: SC 2.5.8 asks that a control be at least 24x24 CSS
 * pixels. A smaller control is still acceptable if it has enough empty space around it
 * — picture a 24px-wide circle centred on it, which must not touch any other control.
 */

export interface TargetRect {
  readonly left: number; readonly top: number;
  readonly right: number; readonly bottom: number;
  readonly width: number; readonly height: number;
}

/**
 * Exceptions a human may ASSERT. "spacing" is deliberately absent: spacing is always
 * computed from geometry. Allowing it as a claim would let a tag bypass the calculation.
 */
export const ASSERTABLE_CLAIMS = ['equivalent', 'inline', 'user-agent-control', 'essential'] as const;
export type ExceptionClaim = (typeof ASSERTABLE_CLAIMS)[number];

/** Only a target verified as an unrotated, unclipped, unoccluded rectangle may auto-pass. */
export type GeometryConfidence = 'verified-rectangular' | 'unverified';

export interface TargetNode {
  readonly index: number;
  readonly label: string;
  readonly rect: TargetRect;
  readonly exceptionClaim: string | null;
  /** Absent or 'unverified' routes the target to manual review, never to a pass. */
  readonly geometryConfidence: GeometryConfidence;
  /** A developer-supplied assertion that two controls do the same thing. NOT trusted. */
  readonly sameActionGroup: string | null;
}

/**
 * A screen-space rectangle that is not itself under assessment but still occupies space
 * — notably the interactive WebGL map cells, which are targets for spacing purposes even
 * though they are not DOM elements. Without these, a small DOM control could be "rescued
 * by spacing" while its circle overlaps a selectable map cell.
 */
export interface Obstacle {
  readonly id: string;
  readonly rect: TargetRect;
  readonly source: 'map-cell' | 'other';
}

/** An obstacle is undersized on the same terms as a target. */
export const obstacleIsUndersized = (o: Obstacle, min: number = AA_MIN): boolean =>
  isUndersized(o.rect, min);

export const AA_MIN = 24;
export const PROJECT_MIN = 44;

/**
 * Rect endpoints must agree with the reported size to within a hair.
 * 1/1024 px (~0.00098) is exactly representable in binary, so boundary tests are
 * deterministic — a decimal epsilon makes `24.01 - 24` evaluate to 0.010000000000001563
 * and the boundary case untestable. It is also tight enough to reject a 23.995px span
 * reported as width 24, which a 1/128 epsilon accepted.
 */
export const DIMENSION_EPSILON = 1 / 1024;

export type SizeVerdict = 'pass' | 'fail' | 'manual-review';

export const isPositiveFinite = (n: number): boolean => Number.isFinite(n) && n > 0;

export function assertValidMin(min: number, name = 'min'): number {
  if (!isPositiveFinite(min)) {
    throw new RangeError(`${name} must be a positive finite number, received ${String(min)}`);
  }
  return min;
}

export function isFiniteRect(r: TargetRect | undefined | null): boolean {
  if (!r) return false;
  const nums = [r.left, r.top, r.right, r.bottom, r.width, r.height];
  for (const n of nums) if (!Number.isFinite(n)) return false;
  if (r.width < 0 || r.height < 0) return false;
  if (Math.abs((r.right - r.left) - r.width) > DIMENSION_EPSILON) return false;
  if (Math.abs((r.bottom - r.top) - r.height) > DIMENSION_EPSILON) return false;
  return true;
}

export function isAssertableClaim(c: string | null | undefined): c is ExceptionClaim {
  if (typeof c !== 'string') return false;
  const trimmed = c.trim();
  for (const valid of ASSERTABLE_CLAIMS) if (valid === trimmed) return true;
  return false;
}

/** A claim attribute is "present" if it is a non-empty string, valid or not. */
export function hasClaimAttribute(c: string | null | undefined): boolean {
  return typeof c === 'string' && c.trim().length > 0;
}

/** Undersized in EITHER dimension. A 100x10 target is undersized. */
export function isUndersized(r: TargetRect, min: number = AA_MIN): boolean {
  return r.width < min || r.height < min;
}

const centreOf = (r: TargetRect): { x: number; y: number } =>
  ({ x: r.left + r.width / 2, y: r.top + r.height / 2 });

/** Circle/rectangle intersection. Exact tangency is NOT an intersection. */
function circleHitsRect(c: { x: number; y: number }, radius: number, r: TargetRect): boolean {
  const nx = Math.max(r.left, Math.min(c.x, r.right));
  const ny = Math.max(r.top, Math.min(c.y, r.bottom));
  return Math.hypot(c.x - nx, c.y - ny) < radius;
}

export function rectsOverlap(a: TargetRect, b: TargetRect): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/** Indexes appearing more than once — identity would be ambiguous. */
export function duplicateIndexes(all: readonly TargetNode[]): number[] {
  const counts = new Map<number, number>();
  for (const t of all) counts.set(t.index, (counts.get(t.index) ?? 0) + 1);
  const dupes: number[] = [];
  for (const [idx, n] of counts) if (n > 1) dupes.push(idx);
  return dupes.sort((a, b) => a - b);
}

export interface OverlapPair {
  readonly a: TargetNode;
  readonly b: TargetNode;
  /** Both sides asserted the same action group. Recorded, never trusted as a pass. */
  readonly sameActionClaimed: boolean;
  readonly claimedGroup: string | null;
}

/**
 * Overlapping controls. W3C allows overlapping regions only where the controls genuinely
 * perform the same action — a fact that must be VERIFIED, not taken from a developer
 * string. A matching `data-a11y-same-action` therefore downgrades the finding's wording
 * but still produces a finding requiring a signed resolution.
 */
export function overlapPairs(all: readonly TargetNode[]): OverlapPair[] {
  const pairs: OverlapPair[] = [];
  for (let i = 0; i < all.length; i++) {
    const a = all[i];
    if (!a || !isFiniteRect(a.rect)) continue;
    for (let j = i + 1; j < all.length; j++) {
      const b = all[j];
      if (!b || !isFiniteRect(b.rect)) continue;
      if (!rectsOverlap(a.rect, b.rect)) continue;
      const same = a.sameActionGroup !== null && a.sameActionGroup === b.sameActionGroup;
      pairs.push({ a, b, sameActionClaimed: same, claimedGroup: same ? a.sameActionGroup : null });
    }
  }
  return pairs;
}

/** Size assessment. A bounding box only measures a target verified as a rectangle. */
export function assessSize(t: TargetNode, min: number = AA_MIN): SizeVerdict {
  assertValidMin(min);
  if (!isFiniteRect(t.rect)) return 'manual-review';
  if (isUndersized(t.rect, min)) return 'fail';
  return t.geometryConfidence === 'verified-rectangular' ? 'pass' : 'manual-review';
}

/**
 * SC 2.5.8 Spacing exception.
 * The circle must clear (a) EVERY other target's rectangle and every obstacle, and
 * additionally (b) another undersized target's circle.
 *
 * `universe` MUST contain every visible target, INCLUDING claim-tagged ones: a claim
 * excuses a target's own size, not its existence as an obstacle. `obstacles` carries
 * non-DOM interactive regions (map cells).
 *
 * Identity is by object reference — `subject` must be an element of `universe`. Index
 * values are report labels and may be duplicated by a faulty collector.
 */
export function meetsSpacingException(
  subject: TargetNode,
  universe: readonly TargetNode[],
  min: number = AA_MIN,
  obstacles: readonly Obstacle[] = []
): boolean {
  assertValidMin(min);
  if (!isFiniteRect(subject.rect)) return false;
  if (!isUndersized(subject.rect, min)) return true;
  const c = centreOf(subject.rect);

  for (const other of universe) {
    if (other === subject) continue;
    if (!isFiniteRect(other.rect)) return false;
    if (circleHitsRect(c, min / 2, other.rect)) return false;
    if (isUndersized(other.rect, min)) {
      const oc = centreOf(other.rect);
      if (Math.hypot(c.x - oc.x, c.y - oc.y) < min) return false;
    }
  }
  for (const ob of obstacles) {
    if (!isFiniteRect(ob.rect)) return false;
    if (circleHitsRect(c, min / 2, ob.rect)) return false;
    // An interactive map cell is a target too: when it is itself undersized, the
    // circle-to-circle test applies exactly as it does between two DOM targets.
    // Omitting it accepted a 10x10 control and a 10x10 cell whose centres were 23px apart.
    if (isUndersized(ob.rect, min)) {
      const oc = { x: ob.rect.left + ob.rect.width / 2, y: ob.rect.top + ob.rect.height / 2 };
      if (Math.hypot(c.x - oc.x, c.y - oc.y) < min) return false;
    }
  }
  return true;
}

export interface ClassifyOptions {
  readonly min?: number;
  readonly projectMin?: number;
  readonly obstacles?: readonly Obstacle[];
}

export interface Classification {
  readonly findings: readonly Finding[];
  readonly totalTargets: number;
  readonly obstacleCount: number;
  readonly passed: readonly TargetNode[];
  readonly rescuedBySpacing: readonly TargetNode[];
}

const rectEvidence = (t: TargetNode): Record<string, string | number | boolean | null> => ({
  label: t.label,
  index: t.index,
  width: t.rect.width,
  height: t.rect.height,
  left: t.rect.left,
  top: t.rect.top
});

export function classifyTargets(
  all: readonly TargetNode[], options: ClassifyOptions = {}
): Classification {
  const min = assertValidMin(options.min ?? AA_MIN, 'min');
  const projectMin = assertValidMin(options.projectMin ?? PROJECT_MIN, 'projectMin');
  const obstacles = options.obstacles ?? [];
  const findings: Finding[] = [];

  for (const idx of duplicateIndexes(all)) {
    findings.push(makeFinding({
      kind: 'collector-duplicate-index', severity: 'data-quality', sc: null,
      detail: `Collector produced index ${idx} more than once; target identity is ambiguous.`,
      evidence: { index: idx }
    }, ['index']));
  }

  const overlaps = overlapPairs(all);
  const overlapping = new Set<TargetNode>();
  for (const pair of overlaps) {
    overlapping.add(pair.a); overlapping.add(pair.b);
    findings.push(makeFinding({
      kind: pair.sameActionClaimed ? 'target-overlap-same-action-claimed' : 'target-overlap',
      severity: 'needs-human-decision', sc: '2.5.8',
      detail: pair.sameActionClaimed
        ? `"${pair.a.label}" and "${pair.b.label}" overlap and both declare same-action group ` +
          `"${pair.claimedGroup ?? ''}". W3C allows overlap only where the controls genuinely ` +
          'perform the same action — verify this rather than trusting the attribute.'
        : `"${pair.a.label}" and "${pair.b.label}" overlap; the overlapping area does not count ` +
          'toward either target.',
      evidence: {
        a: pair.a.label, b: pair.b.label, aIndex: pair.a.index, bIndex: pair.b.index,
        sameActionClaimed: pair.sameActionClaimed, claimedGroup: pair.claimedGroup
      }
    }, ['a', 'b', 'aIndex', 'bIndex']));
  }

  const passed: TargetNode[] = [];
  const rescued: TargetNode[] = [];

  for (const t of all) {
    if (!isFiniteRect(t.rect)) {
      findings.push(makeFinding({
        kind: 'target-invalid-geometry', severity: 'data-quality', sc: null,
        detail: `"${t.label}" reported geometry that is not finite or not self-consistent.`,
        evidence: rectEvidence(t)
      }, ['label', 'index']));
      continue;
    }

    if (hasClaimAttribute(t.exceptionClaim) && !isAssertableClaim(t.exceptionClaim)) {
      findings.push(makeFinding({
        kind: 'target-invalid-claim', severity: 'data-quality', sc: '2.5.8',
        detail: `"${t.label}" claims exception "${t.exceptionClaim ?? ''}", which is not one of ` +
                `${ASSERTABLE_CLAIMS.join(', ')}. The claim exempts nothing.`,
        evidence: { ...rectEvidence(t), claim: t.exceptionClaim }
      }, ['label', 'index', 'claim']));
    }

    // Project rule (44px) applies to every target, tagged or not.
    if (isUndersized(t.rect, projectMin)) {
      findings.push(makeFinding({
        kind: 'project-rule-shortfall', severity: 'project-requirement', sc: null,
        detail: `"${t.label}" is ${t.rect.width}x${t.rect.height}, below the ${projectMin}px ` +
                'BRERC build-brief minimum.',
        evidence: rectEvidence(t)
      }, ['label', 'index']));
    } else if (t.geometryConfidence !== 'verified-rectangular' || overlapping.has(t)) {
      findings.push(makeFinding({
        kind: 'project-rule-manual-review', severity: 'needs-human-decision', sc: null,
        detail: `"${t.label}" clears ${projectMin}px by bounding box, but the box overstates the ` +
                'target (non-rectangular, clipped or overlapped). Measure the real hit area.',
        evidence: rectEvidence(t)
      }, ['label', 'index']));
    }

    if (isAssertableClaim(t.exceptionClaim)) {
      findings.push(makeFinding({
        kind: 'target-exception-claimed', severity: 'needs-human-decision', sc: '2.5.8',
        detail: `"${t.label}" claims the "${t.exceptionClaim}" exception. A named reviewer must ` +
                'confirm it applies.',
        evidence: { ...rectEvidence(t), claim: t.exceptionClaim }
      }, ['label', 'index', 'claim']));
      continue;   // tagged targets are not WCAG subjects, but remain obstacles above
    }

    const verdict = assessSize(t, min);
    if (verdict === 'manual-review' || overlapping.has(t)) {
      findings.push(makeFinding({
        kind: 'target-manual-review', severity: 'needs-human-decision', sc: '2.5.8',
        detail: `"${t.label}" cannot be decided from its bounding box (${t.geometryConfidence}` +
                `${overlapping.has(t) ? ', overlapped' : ''}). Measure the real hit area.`,
        evidence: { ...rectEvidence(t), geometryConfidence: t.geometryConfidence }
      }, ['label', 'index']));
      continue;
    }

    if (verdict === 'fail') {
      if (meetsSpacingException(t, all, min, obstacles)) {
        rescued.push(t);
      } else {
        findings.push(makeFinding({
          kind: 'target-undersized', severity: 'wcag-nonconformance', sc: '2.5.8',
          detail: `"${t.label}" is ${t.rect.width}x${t.rect.height} (below ${min}x${min}) and does ` +
                  'not have the clearance required by the Spacing exception.',
          evidence: rectEvidence(t)
        }, ['label', 'index']));
      }
      continue;
    }
    passed.push(t);
  }

  return {
    findings,
    totalTargets: all.length,
    obstacleCount: obstacles.length,
    passed,
    rescuedBySpacing: rescued
  };
}
