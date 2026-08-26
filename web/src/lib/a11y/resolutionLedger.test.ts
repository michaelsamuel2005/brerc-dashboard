import { describe, it, expect } from 'vitest';
import {
  applyLedger, validateResolution, describeBlockers, parseResolutionLedger,
  ResolutionLedgerError,
  type Resolution, type ResolutionScope
} from './resolutionLedger';
import { makeFinding, type Finding, type Severity } from './findings';
import { first } from './testUtil';

const SCOPE: ResolutionScope = {
  project: 'a11y-chromium-V1-320x640',
  viewport: '320x640',
  state: 'cell-selected',
  camera: 'initial-z12',
  dataMode: 'msw-mock'
};
const OTHER_SCOPE: ResolutionScope = {
  ...SCOPE,
  project: 'a11y-webkit-V3-390x844',
  viewport: '390x844'
};

const finding = (label: string, width = 16,
                 severity: Severity = 'needs-human-decision'): Finding => makeFinding({
  kind: severity === 'wcag-nonconformance' ? 'target-undersized' : 'target-manual-review',
  severity, sc: '2.5.8', detail: `${label} needs review`,
  evidence: { label, index: 1, width }
}, ['label', 'index']);

const sign = (f: Finding, over: Partial<Resolution> = {}): Resolution => ({
  findingId: f.id, fingerprint: f.fingerprint, outcome: 'dismissed',
  reviewer: 'Michael Samuel', date: '2026-07-26',
  justification: 'Measured the real hit area on a Pixel 7; 46px, comfortably compliant.',
  scope: SCOPE, ...over
});

describe('the gate is reachable but not subvertible', () => {
  it('a run with no findings is resolved', () => {
    expect(applyLedger([], [], SCOPE).ledgerResolved).toBe(true);
  });
  it('an unresolved finding blocks', () => {
    const f = finding('Zoom in');
    expect(applyLedger([f], [], SCOPE).ledgerResolved).toBe(false);
  });
  it('a validly dismissed human-decision finding clears', () => {
    const f = finding('Zoom in');
    expect(applyLedger([f], [sign(f)], SCOPE).ledgerResolved).toBe(true);
  });
  it('a confirmed defect keeps blocking until the code is fixed', () => {
    const f = finding('Zoom in');
    const app = applyLedger([f], [sign(f, { outcome: 'confirmed' })], SCOPE);
    expect(app.ledgerResolved).toBe(false);
    expect(app.confirmedDefects).toHaveLength(1);
  });
});

describe('a deterministic WCAG failure cannot be dismissed', () => {
  it('rejects a dismissal of a wcag-nonconformance', () => {
    const f = finding('Tiny button', 16, 'wcag-nonconformance');
    const app = applyLedger([f], [sign(f)], SCOPE);
    expect(first(app.invalid).problems).toContain('severity-not-dismissible');
    expect(app.ledgerResolved).toBe(false);
    expect(app.resolved).toHaveLength(0);
  });
  it('still allows CONFIRMING a wcag-nonconformance', () => {
    const f = finding('Tiny button', 16, 'wcag-nonconformance');
    const app = applyLedger([f], [sign(f, { outcome: 'confirmed' })], SCOPE);
    expect(app.invalid).toHaveLength(0);
    expect(app.confirmedDefects).toHaveLength(1);
    expect(app.ledgerResolved).toBe(false);
  });
  it.each(['project-requirement', 'data-quality'] as const)(
    'rejects a dismissal of a %s finding', severity => {
      const f = finding('X', 16, severity);
      expect(first(applyLedger([f], [sign(f)], SCOPE).invalid).problems)
        .toContain('severity-not-dismissible');
    });
});

describe('outcome is validated at runtime, not just by types', () => {
  it.each(['waived', 'ok', '', 'DISMISSED', 'accepted'])(
    'rejects the hand-edited outcome %s', bad => {
      const f = finding('Zoom in');
      const r = { ...sign(f), outcome: bad } as unknown as Resolution;
      const app = applyLedger([f], [r], SCOPE);
      expect(first(app.invalid).problems).toContain('invalid-outcome');
      expect(app.ledgerResolved).toBe(false);
    });
  it('rejects a missing outcome', () => {
    const f = finding('Zoom in');
    const r = { ...sign(f) } as Record<string, unknown>;
    delete r['outcome'];
    const app = applyLedger([f], [r as unknown as Resolution], SCOPE);
    expect(first(app.invalid).problems).toContain('invalid-outcome');
  });
});

describe('scoping across the viewport and state matrix', () => {
  it('the same finding at two viewports is resolved independently', () => {
    const at320 = finding('Zoom in', 16);
    const at390 = finding('Zoom in', 18);      // same id, different evidence
    expect(at390.id).toBe(at320.id);
    expect(at390.fingerprint).not.toBe(at320.fingerprint);
    const ledger = [sign(at320), sign(at390, { scope: OTHER_SCOPE })];
    expect(applyLedger([at320], ledger, SCOPE).ledgerResolved).toBe(true);
    expect(applyLedger([at390], ledger, OTHER_SCOPE).ledgerResolved).toBe(true);
  });
  it('two entries for the same id in DIFFERENT scopes are not duplicates', () => {
    const f = finding('Zoom in');
    const app = applyLedger([f], [sign(f), sign(f, { scope: OTHER_SCOPE })], SCOPE);
    expect(app.invalid).toHaveLength(0);
  });
  it('separates engines at the same viewport', () => {
    const f = finding('Zoom in');
    const webkit: ResolutionScope = {
      ...SCOPE,
      project: 'a11y-webkit-V1-320x640'
    };
    const app = applyLedger([f], [sign(f), sign(f, { scope: webkit })], SCOPE);
    expect(app.invalid).toHaveLength(0);
    expect(app.ledgerResolved).toBe(true);
  });
  it('separates scheduled cameras in the same project and state', () => {
    const atMin = finding('Cell A', 45);
    const atMax = finding('Cell A', 180);
    expect(atMax.id).toBe(atMin.id);
    const maxScope: ResolutionScope = { ...SCOPE, camera: 'max-z14' };
    const ledger = [sign(atMin), sign(atMax, { scope: maxScope })];
    expect(applyLedger([atMin], ledger, SCOPE).ledgerResolved).toBe(true);
    expect(applyLedger([atMax], ledger, maxScope).ledgerResolved).toBe(true);
  });
  it('two entries for the same id in the SAME scope are duplicates', () => {
    const f = finding('Zoom in');
    expect(first(applyLedger([f], [sign(f), sign(f)], SCOPE).invalid).problems)
      .toContain('duplicate-resolution');
  });
  it('an entry for a state where the finding is absent is ignored, not "unknown-finding"', () => {
    const f = finding('Zoom in');
    const otherState: ResolutionScope = { ...SCOPE, state: 'empty', camera: 'not-applicable' };
    const app = applyLedger([], [sign(f, { scope: otherState })], SCOPE);
    expect(app.invalid).toHaveLength(0);
    expect(app.ledgerResolved).toBe(true);
  });
  it('an entry in THIS scope for a finding that does not exist is an error', () => {
    const f = finding('Zoom in');
    expect(first(applyLedger([], [sign(f)], SCOPE).invalid).problems).toContain('unknown-finding');
  });
  it('an entry with no scope at all is invalid', () => {
    const f = finding('Zoom in');
    const r = { ...sign(f) } as Record<string, unknown>;
    delete r['scope'];
    expect(first(applyLedger([f], [r as unknown as Resolution], SCOPE).invalid).problems)
      .toContain('missing-scope');
  });
  it('reports the scope it was applied for', () => {
    expect(applyLedger([], [], SCOPE).scope).toEqual(SCOPE);
  });
});

describe('staleness', () => {
  it('a resolution signed against different evidence goes stale', () => {
    const before = finding('Zoom in', 16);
    const after = finding('Zoom in', 12);
    const app = applyLedger([after], [sign(before)], SCOPE);
    expect(app.stale).toHaveLength(1);
    expect(app.ledgerResolved).toBe(false);
  });
  it('re-signing against current evidence clears it', () => {
    const after = finding('Zoom in', 12);
    expect(applyLedger([after], [sign(after)], SCOPE).ledgerResolved).toBe(true);
  });
});

describe('entry validation', () => {
  const f = finding('Zoom in');
  const byId = new Map([[f.id, f]]);
  it('requires a named reviewer', () => {
    expect(validateResolution(sign(f, { reviewer: '  ' }), byId, SCOPE)).toContain('missing-reviewer');
  });
  it('requires a justification', () => {
    expect(validateResolution(sign(f, { justification: '' }), byId, SCOPE)).toContain('missing-justification');
  });
  it('rejects a token justification', () => {
    expect(validateResolution(sign(f, { justification: 'fine' }), byId, SCOPE)).toContain('justification-too-short');
  });
  it('accepts exactly the minimum length', () => {
    expect(validateResolution(sign(f, { justification: 'x'.repeat(20) }), byId, SCOPE)).toHaveLength(0);
  });
  it('rejects one character short', () => {
    expect(validateResolution(sign(f, { justification: 'x'.repeat(19) }), byId, SCOPE))
      .toContain('justification-too-short');
  });
  it('requires an ISO date', () => {
    expect(validateResolution(sign(f, { date: '26/07/2026' }), byId, SCOPE)).toContain('invalid-date');
    expect(validateResolution(sign(f, { date: '2026-13-45' }), byId, SCOPE)).toContain('invalid-date');
  });
  it('rejects a calendar date that JavaScript would otherwise roll into March', () => {
    expect(validateResolution(sign(f, { date: '2026-02-31' }), byId, SCOPE))
      .toContain('invalid-date');
  });
  it('accepts a full ISO timestamp', () => {
    expect(validateResolution(sign(f, { date: '2026-07-26T09:15:00Z' }), byId, SCOPE)).toHaveLength(0);
  });
});

describe('blocker descriptions name the scope', () => {
  it('includes viewport and state', () => {
    const f = finding('Zoom in');
    const text = first(describeBlockers(applyLedger([f], [], SCOPE)));
    expect(text).toContain('a11y-chromium-V1-320x640');
    expect(text).toContain('320x640 / cell-selected / initial-z12 / msw-mock');
  });
  it('marks a confirmed defect as requiring a fix', () => {
    const f = finding('Zoom in');
    expect(first(describeBlockers(applyLedger([f], [sign(f, { outcome: 'confirmed' })], SCOPE))))
      .toContain('fix required');
  });
  it('produces nothing for a clean run', () => {
    expect(describeBlockers(applyLedger([], [], SCOPE))).toHaveLength(0);
  });
});

describe('runtime JSON boundary', () => {
  const f = finding('Zoom in');
  it('accepts a structurally valid ledger', () => {
    expect(parseResolutionLedger({ resolutions: [sign(f)] })).toHaveLength(1);
  });
  it('rejects a missing or non-array resolutions property', () => {
    expect(() => parseResolutionLedger({})).toThrow(ResolutionLedgerError);
    expect(() => parseResolutionLedger({ resolutions: {} })).toThrow(ResolutionLedgerError);
  });
  it('rejects malformed entries even when they belong to another scope', () => {
    const malformed = {
      ...sign(f, { scope: OTHER_SCOPE }),
      outcome: 'waived',
      reviewer: ''
    };
    expect(() => parseResolutionLedger({ resolutions: [malformed] })).toThrow(/invalid-outcome/);
  });
  it('rejects duplicate finding records in one complete scope', () => {
    expect(() => parseResolutionLedger({ resolutions: [sign(f), sign(f)] }))
      .toThrow(/duplicate-resolution/);
  });
  it('rejects a typo scope against an exact allowed matrix', () => {
    const typo = sign(f, { scope: { ...SCOPE, state: 'defualt' } });
    expect(() => parseResolutionLedger(
      { resolutions: [typo] },
      {
        projects: [SCOPE.project],
        viewports: [SCOPE.viewport],
        states: [SCOPE.state],
        cameras: [SCOPE.camera],
        dataModes: [SCOPE.dataMode],
        scopes: [SCOPE]
      }
    )).toThrow(/unknown-scope-value/);
  });
});
