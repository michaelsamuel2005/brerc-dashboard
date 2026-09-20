import { describe, it, expect } from 'vitest';
import {
  meetsSpacingException, classifyTargets, assessSize, isFiniteRect, isAssertableClaim,
  isUndersized, duplicateIndexes, overlapPairs, rectsOverlap, assertValidMin, hasClaimAttribute,
  AA_MIN, PROJECT_MIN, DIMENSION_EPSILON, ASSERTABLE_CLAIMS,
  type TargetNode, type Obstacle
} from './targetSpacing';
import { mk, rect, resetIndexes, first, at, countKind } from './testUtil';

const obstacle = (id: string, l: number, t: number, w: number, h: number): Obstacle =>
  ({ id, rect: rect(l, t, w, h), source: 'map-cell' });

describe('isUndersized — one-dimensional failures', () => {
  // The "|| -> &&" mutant survived an earlier suite because every case was undersized in
  // BOTH dimensions, making the operators indistinguishable. These pin each dimension.
  it('a 100x10 target is undersized (height only)', () => {
    expect(isUndersized(rect(0, 0, 100, 10))).toBe(true);
  });
  it('a 10x100 target is undersized (width only)', () => {
    expect(isUndersized(rect(0, 0, 10, 100))).toBe(true);
  });
  it('a 100x100 target is not undersized', () => {
    expect(isUndersized(rect(0, 0, 100, 100))).toBe(false);
  });
  it('assessSize fails a 100x10 target', () => {
    resetIndexes(); expect(assessSize(mk(0, 0, 100, 10))).toBe('fail');
  });
  it('assessSize fails a 10x100 target', () => {
    resetIndexes(); expect(assessSize(mk(0, 0, 10, 100))).toBe('fail');
  });
  it('a lone 100x10 target is undersized yet rescued by spacing', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 100, 10), mk(0, 300, 44, 44)]);
    expect(r.rescuedBySpacing).toHaveLength(1);
    expect(countKind(r.findings, 'target-undersized')).toBe(0);
  });
  it('a 100x10 target with a close neighbour is a non-conformance', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 100, 10), mk(0, 14, 100, 10)]);
    expect(countKind(r.findings, 'target-undersized')).toBe(2);
  });
  it('exactly 24x24 passes; 23.9 in either dimension fails', () => {
    resetIndexes();
    expect(assessSize(mk(0, 0, 24, 24))).toBe('pass');
    expect(assessSize(mk(0, 0, 23.9, 24))).toBe('fail');
    expect(assessSize(mk(0, 0, 24, 23.9))).toBe('fail');
  });
});

describe('spacing exception — historical regressions', () => {
  it('v2: elongated neighbour, far centre but close edge', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10), mk(12, 0, 100, 10)];
    expect(meetsSpacingException(first(u), u)).toBe(false);
  });
  it('v3: claim-tagged neighbour still counts as an obstacle', () => {
    resetIndexes();
    const u = [mk(0, 0, 10, 10), mk(15, 0, 10, 10, { exceptionClaim: 'essential' })];
    expect(meetsSpacingException(first(u), u)).toBe(false);
  });
  it('well-separated small targets pass', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10), mk(60, 0, 10, 10)];
    expect(meetsSpacingException(first(u), u)).toBe(true);
  });
});

describe('spacing exception — branch isolation and boundaries', () => {
  it('two 1x1 targets 20px apart exercise the circle-to-circle branch alone', () => {
    resetIndexes(); const u = [mk(0, 0, 1, 1), mk(20, 0, 1, 1)];
    expect(meetsSpacingException(first(u), u)).toBe(false);
  });
  it('centre distance exactly 24 passes (tangency is not intersection)', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10), mk(24, 0, 10, 10)];
    expect(meetsSpacingException(first(u), u)).toBe(true);
  });
  it('centre distance just below 24 fails', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10), mk(23.9, 0, 10, 10)];
    expect(meetsSpacingException(first(u), u)).toBe(false);
  });
  it('circle-to-rect clearance exactly 12 passes', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10), mk(17, 0, 44, 44)];
    expect(meetsSpacingException(first(u), u)).toBe(true);
  });
  it('circle-to-rect clearance just below 12 fails', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10), mk(16.9, 0, 44, 44)];
    expect(meetsSpacingException(first(u), u)).toBe(false);
  });
  it('an adequately sized subject passes regardless of neighbours', () => {
    resetIndexes(); const u = [mk(0, 0, 44, 44), mk(45, 0, 10, 10)];
    expect(meetsSpacingException(first(u), u)).toBe(true);
  });
});

describe('map cells participate as spacing obstacles', () => {
  it('an isolated small control is rescued when no map cell is near', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10)];
    expect(meetsSpacingException(first(u), u, AA_MIN, [obstacle('far', 200, 200, 50, 50)])).toBe(true);
  });
  it('the same control fails when an interactive map cell intrudes on its circle', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10)];
    expect(meetsSpacingException(first(u), u, AA_MIN, [obstacle('near', 14, 0, 50, 50)])).toBe(false);
  });
  it('an obstacle with invalid geometry prevents a pass', () => {
    resetIndexes(); const u = [mk(0, 0, 10, 10)];
    const bad: Obstacle = { id: 'bad', source: 'map-cell',
      rect: { left: 0, top: 0, right: NaN, bottom: 5, width: NaN, height: 5 } };
    expect(meetsSpacingException(first(u), u, AA_MIN, [bad])).toBe(false);
  });
  it('classifyTargets threads obstacles through and reports the count', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 10, 10)], { obstacles: [obstacle('near', 14, 0, 50, 50)] });
    expect(r.obstacleCount).toBe(1);
    expect(countKind(r.findings, 'target-undersized')).toBe(1);
    expect(r.rescuedBySpacing).toHaveLength(0);
  });
});

describe('identity', () => {
  it('uses object reference, so duplicate indexes cannot rescue a target', () => {
    resetIndexes();
    const a = mk(0, 0, 10, 10, { index: 0 });
    const b = mk(14, 0, 10, 10, { index: 0 });
    expect(a.index).toBe(b.index);
    expect(meetsSpacingException(a, [a, b])).toBe(false);
  });
  it('reports duplicate indexes as a data-quality finding', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 44, 44, { index: 0 }), mk(200, 0, 44, 44, { index: 0 })]);
    expect(countKind(r.findings, 'collector-duplicate-index')).toBe(1);
  });
  it('finds no duplicates in a well-formed collection', () => {
    resetIndexes();
    expect(duplicateIndexes([mk(0, 0, 44, 44), mk(200, 0, 44, 44)])).toEqual([]);
  });
  it('reports every duplicated index, sorted', () => {
    resetIndexes();
    const u = [mk(0, 0, 44, 44, { index: 5 }), mk(100, 0, 44, 44, { index: 5 }),
               mk(200, 0, 44, 44, { index: 2 }), mk(300, 0, 44, 44, { index: 2 })];
    expect(duplicateIndexes(u)).toEqual([2, 5]);
  });
});

describe('exception claims', () => {
  it('does not accept "spacing" — spacing is always computed, never asserted', () => {
    expect(isAssertableClaim('spacing')).toBe(false);
    expect([...ASSERTABLE_CLAIMS]).not.toContain('spacing');
  });
  it('accepts only the four assertable exceptions', () => {
    for (const c of ['equivalent', 'inline', 'user-agent-control', 'essential']) {
      expect(isAssertableClaim(c)).toBe(true);
    }
    for (const c of ['', '   ', 'because-design-said-so', 'spacing', null, undefined]) {
      expect(isAssertableClaim(c)).toBe(false);
    }
  });
  it('tolerates surrounding whitespace in a valid claim', () => {
    expect(isAssertableClaim('  essential  ')).toBe(true);
  });
  it('distinguishes an absent attribute from an invalid one', () => {
    expect(hasClaimAttribute(null)).toBe(false);
    expect(hasClaimAttribute('')).toBe(false);
    expect(hasClaimAttribute('   ')).toBe(false);
    expect(hasClaimAttribute('nonsense')).toBe(true);
  });
  it('a "spacing" tag does not bypass the calculation', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 10, 10, { exceptionClaim: 'spacing' }), mk(14, 0, 10, 10)]);
    expect(countKind(r.findings, 'target-invalid-claim')).toBe(1);
    expect(countKind(r.findings, 'target-undersized')).toBe(2);
    expect(countKind(r.findings, 'target-exception-claimed')).toBe(0);
  });
  it('a valid claim produces a finding requiring a signed resolution', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 10, 10, { exceptionClaim: 'essential' }), mk(300, 0, 44, 44)]);
    expect(countKind(r.findings, 'target-exception-claimed')).toBe(1);
    expect(countKind(r.findings, 'target-undersized')).toBe(0);
    expect(countKind(r.findings, 'project-rule-shortfall')).toBe(1);
  });
});

describe('overlap — same-action is recorded, never trusted', () => {
  it('detects an overlapping pair', () => {
    resetIndexes();
    expect(overlapPairs([mk(0, 0, 24, 24), mk(12, 12, 24, 24)])).toHaveLength(1);
  });
  it('two overlapping 24x24 controls do not produce a clean report', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 24, 24), mk(12, 12, 24, 24)]);
    expect(countKind(r.findings, 'target-overlap')).toBe(1);
    expect(r.passed).toHaveLength(0);
  });
  it('a matching same-action claim still yields a finding, flagged for verification', () => {
    resetIndexes();
    const r = classifyTargets([
      mk(0, 0, 24, 24, { sameActionGroup: 'zoom' }),
      mk(12, 12, 24, 24, { sameActionGroup: 'zoom' })
    ]);
    expect(countKind(r.findings, 'target-overlap-same-action-claimed')).toBe(1);
    expect(countKind(r.findings, 'target-overlap')).toBe(0);
    expect(r.passed).toHaveLength(0);       // NOT a clean report
  });
  it('records the claimed group in the evidence', () => {
    resetIndexes();
    const pairs = overlapPairs([
      mk(0, 0, 24, 24, { sameActionGroup: 'zoom' }),
      mk(12, 12, 24, 24, { sameActionGroup: 'zoom' })
    ]);
    expect(first(pairs).sameActionClaimed).toBe(true);
    expect(first(pairs).claimedGroup).toBe('zoom');
  });
  it('flags overlap when only one side declares a group', () => {
    resetIndexes();
    const pairs = overlapPairs([mk(0, 0, 24, 24, { sameActionGroup: 'zoom' }), mk(12, 12, 24, 24)]);
    expect(first(pairs).sameActionClaimed).toBe(false);
  });
  it('flags overlap when the groups differ', () => {
    resetIndexes();
    const pairs = overlapPairs([
      mk(0, 0, 24, 24, { sameActionGroup: 'in' }), mk(12, 12, 24, 24, { sameActionGroup: 'out' })
    ]);
    expect(first(pairs).sameActionClaimed).toBe(false);
  });
  it('treats null groups on both sides as no claim', () => {
    resetIndexes();
    const pairs = overlapPairs([mk(0, 0, 24, 24), mk(12, 12, 24, 24)]);
    expect(first(pairs).sameActionClaimed).toBe(false);
  });
  it('reports each overlapping pair once, not twice', () => {
    resetIndexes();
    expect(overlapPairs([mk(0, 0, 24, 24), mk(12, 12, 24, 24), mk(500, 0, 24, 24)])).toHaveLength(1);
  });
});

describe('rectsOverlap — tangency', () => {
  it('edge-to-edge horizontally is not an overlap', () => {
    expect(rectsOverlap(rect(0, 0, 24, 24), rect(24, 0, 24, 24))).toBe(false);
  });
  it('edge-to-edge vertically is not an overlap', () => {
    expect(rectsOverlap(rect(0, 0, 24, 24), rect(0, 24, 24, 24))).toBe(false);
  });
  it('one pixel of intrusion is an overlap', () => {
    expect(rectsOverlap(rect(0, 0, 24, 24), rect(23, 0, 24, 24))).toBe(true);
  });
});

describe('geometry confidence', () => {
  it('only a verified rectangle may auto-pass', () => {
    resetIndexes(); expect(assessSize(mk(0, 0, 24, 24))).toBe('pass');
  });
  it('unverified geometry is manual review, never a pass', () => {
    resetIndexes();
    expect(assessSize(mk(0, 0, 24, 24, { geometryConfidence: 'unverified' }))).toBe('manual-review');
  });
  it('an undersized box fails whatever the shape', () => {
    resetIndexes();
    expect(assessSize(mk(0, 0, 20, 20, { geometryConfidence: 'unverified' }))).toBe('fail');
  });
  it('non-rectangular 44px+ targets get a project-level manual review', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 50, 50, { geometryConfidence: 'unverified' })]);
    expect(countKind(r.findings, 'project-rule-manual-review')).toBe(1);
    expect(countKind(r.findings, 'project-rule-shortfall')).toBe(0);
  });
  it('an undersized target is not also given a project manual review', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 10, 10, { geometryConfidence: 'unverified' })]);
    expect(countKind(r.findings, 'project-rule-manual-review')).toBe(0);
    expect(countKind(r.findings, 'project-rule-shortfall')).toBe(1);
  });
});

describe('isFiniteRect — fields, epsilon and boundaries', () => {
  const base = rect(0, 0, 24, 24);
  it.each(['left', 'top', 'right', 'bottom', 'width', 'height'])(
    'rejects a rect whose %s alone is NaN', field => {
      expect(isFiniteRect({ ...base, [field]: NaN })).toBe(false);
    });
  it('rejects an infinite field', () => {
    expect(isFiniteRect({ ...base, right: Infinity, width: Infinity })).toBe(false);
  });
  it('rejects a negative dimension', () => {
    expect(isFiniteRect({ left: 0, top: 5, right: 24, bottom: 5, width: 24, height: -0.5 })).toBe(false);
  });
  it('accepts a zero-width rect as finite (degenerate, filtered elsewhere)', () => {
    expect(isFiniteRect({ left: 5, top: 0, right: 5, bottom: 24, width: 0, height: 24 })).toBe(true);
  });
  it('accepts drift of exactly the epsilon', () => {
    expect(isFiniteRect({ ...base, right: 24 + DIMENSION_EPSILON })).toBe(true);
  });
  it('rejects drift just beyond the epsilon', () => {
    expect(isFiniteRect({ ...base, right: 24 + DIMENSION_EPSILON * 2 })).toBe(false);
  });
  it('rejects a 23.995px span reported as width 24', () => {
    expect(isFiniteRect({ left: 0, top: 0, right: 23.995, bottom: 24, width: 24, height: 24 })).toBe(false);
  });
  it('rejects the same defect on the vertical axis', () => {
    expect(isFiniteRect({ left: 0, top: 0, right: 24, bottom: 23.995, width: 24, height: 24 })).toBe(false);
  });
  it('rejects null and undefined', () => {
    expect(isFiniteRect(null)).toBe(false);
    expect(isFiniteRect(undefined)).toBe(false);
  });
  it('reports invalid geometry rather than passing it', () => {
    resetIndexes();
    const bad: TargetNode = {
      index: 0, label: 'bad', exceptionClaim: null, sameActionGroup: null,
      geometryConfidence: 'verified-rectangular',
      rect: { left: 0, top: 0, right: NaN, bottom: 10, width: NaN, height: 10 }
    };
    const r = classifyTargets([bad, mk(300, 0, 44, 44)]);
    expect(countKind(r.findings, 'target-invalid-geometry')).toBe(1);
    expect(countKind(r.findings, 'target-undersized')).toBe(0);
  });
});

describe('threshold validation', () => {
  it.each([NaN, 0, -1, Infinity, -Infinity])('rejects a non-positive-finite min (%s)', bad => {
    expect(() => assertValidMin(bad)).toThrow(RangeError);
    resetIndexes();
    expect(() => classifyTargets([mk(0, 0, 10, 10)], { min: bad })).toThrow(RangeError);
  });
  it('rejects a non-positive-finite projectMin', () => {
    resetIndexes();
    expect(() => classifyTargets([mk(0, 0, 10, 10)], { projectMin: NaN })).toThrow(RangeError);
  });
  it('rejects a bad min inside meetsSpacingException too', () => {
    resetIndexes();
    const u = [mk(0, 0, 10, 10)];
    expect(() => meetsSpacingException(first(u), u, NaN)).toThrow(RangeError);
  });
  it('uses the documented defaults', () => {
    expect(AA_MIN).toBe(24);
    expect(PROJECT_MIN).toBe(44);
  });
  it('honours a custom min', () => {
    // At min=44 the 30x30 control is undersized, and a neighbour 30px away intrudes on
    // its 44px-diameter circle (radius 22), so the Spacing exception cannot rescue it.
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 30, 30), mk(30, 0, 60, 60)], { min: 44, projectMin: 44 });
    expect(countKind(r.findings, 'target-undersized')).toBe(1);
  });
  it('a wider gap rescues the same target at the same custom min', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 30, 30), mk(300, 0, 60, 60)], { min: 44, projectMin: 44 });
    expect(countKind(r.findings, 'target-undersized')).toBe(0);
    expect(r.rescuedBySpacing).toHaveLength(1);
  });
});

describe('a clean collection', () => {
  it('produces no findings at all', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 44, 44), mk(200, 0, 44, 44)]);
    expect(r.findings).toHaveLength(0);
    expect(r.passed).toHaveLength(2);
  });
  it('counts targets and obstacles', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 44, 44), mk(200, 0, 44, 44)],
                              { obstacles: [obstacle('c', 900, 900, 40, 40)] });
    expect(r.totalTargets).toBe(2);
    expect(r.obstacleCount).toBe(1);
  });
  it('lists the passing targets in order', () => {
    resetIndexes();
    const r = classifyTargets([mk(0, 0, 44, 44), mk(200, 0, 44, 44)]);
    expect(at(r.passed, 1).label).toBe('t1');
  });
});

// ── Added after a mutation sweep showed these predicates unprotected ────────────

describe('isFiniteRect — each dimension guard independently', () => {
  const base = rect(0, 0, 24, 24);
  it('rejects a negative width alone', () => {
    expect(isFiniteRect({ ...base, left: 5, right: 0, width: -5 })).toBe(false);
  });
  it('rejects a negative height alone', () => {
    expect(isFiniteRect({ ...base, top: 5, bottom: 0, height: -5 })).toBe(false);
  });
  it('accepts a zero height (degenerate, filtered elsewhere)', () => {
    expect(isFiniteRect({ left: 0, top: 5, right: 24, bottom: 5, width: 24, height: 0 })).toBe(true);
  });
});

describe('rectsOverlap — all four edges', () => {
  it('is symmetric: b tangent to the right of a', () => {
    expect(rectsOverlap(rect(24, 0, 24, 24), rect(0, 0, 24, 24))).toBe(false);
  });
  it('is symmetric: b tangent below a', () => {
    expect(rectsOverlap(rect(0, 24, 24, 24), rect(0, 0, 24, 24))).toBe(false);
  });
  it('detects intrusion from the right', () => {
    expect(rectsOverlap(rect(23, 0, 24, 24), rect(0, 0, 24, 24))).toBe(true);
  });
  it('detects intrusion from below', () => {
    expect(rectsOverlap(rect(0, 23, 24, 24), rect(0, 0, 24, 24))).toBe(true);
  });
});

describe('meetsSpacingException — invalid geometry can never be shown to pass', () => {
  it('returns false for a subject with invalid geometry', () => {
    const bad: TargetNode = {
      index: 0, label: 'bad', exceptionClaim: null, sameActionGroup: null,
      geometryConfidence: 'verified-rectangular',
      rect: { left: 0, top: 0, right: NaN, bottom: 10, width: NaN, height: 10 }
    };
    expect(meetsSpacingException(bad, [bad])).toBe(false);
  });
  it('returns false when an obstacle target has invalid geometry', () => {
    resetIndexes();
    const subject = mk(0, 0, 10, 10);
    const badNeighbour: TargetNode = {
      index: 99, label: 'bad', exceptionClaim: null, sameActionGroup: null,
      geometryConfidence: 'verified-rectangular',
      rect: { left: 900, top: 0, right: NaN, bottom: 10, width: NaN, height: 10 }
    };
    expect(meetsSpacingException(subject, [subject, badNeighbour])).toBe(false);
  });
});

describe('cross-surface spacing — map cells are targets too', () => {
  it('fails a 10x10 control whose centre is 23px from an undersized map cell', () => {
    // Rect test alone passes here (edge clearance 18px > 12px radius); only the
    // circle-to-circle test catches it. This case was accepted before the fix.
    resetIndexes();
    const u = [mk(0, 0, 10, 10)];
    const cell: Obstacle = { id: 'map-cell:A', source: 'map-cell', rect: rect(23, 0, 10, 10) };
    expect(meetsSpacingException(first(u), u, AA_MIN, [cell])).toBe(false);
  });
  it('passes when the undersized cell centre is exactly 24px away', () => {
    resetIndexes();
    const u = [mk(0, 0, 10, 10)];
    const cell: Obstacle = { id: 'map-cell:A', source: 'map-cell', rect: rect(24, 0, 10, 10) };
    expect(meetsSpacingException(first(u), u, AA_MIN, [cell])).toBe(true);
  });
  it('an adequately sized cell only needs the rectangle test', () => {
    resetIndexes();
    const u = [mk(0, 0, 10, 10)];
    const big: Obstacle = { id: 'map-cell:B', source: 'map-cell', rect: rect(18, 0, 60, 60) };
    expect(meetsSpacingException(first(u), u, AA_MIN, [big])).toBe(true);
    const closer: Obstacle = { id: 'map-cell:C', source: 'map-cell', rect: rect(16, 0, 60, 60) };
    expect(meetsSpacingException(first(u), u, AA_MIN, [closer])).toBe(false);
  });
  it('reports the control as a non-conformance through classifyTargets', () => {
    resetIndexes();
    const cell: Obstacle = { id: 'map-cell:A', source: 'map-cell', rect: rect(23, 0, 10, 10) };
    const r = classifyTargets([mk(0, 0, 10, 10)], { obstacles: [cell] });
    expect(countKind(r.findings, 'target-undersized')).toBe(1);
  });
});
