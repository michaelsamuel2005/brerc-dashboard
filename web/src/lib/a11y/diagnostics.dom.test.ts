import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  collectProvenance, collectReflow, toggleDomTextSpacing, toggleSvgTextSpacing,
  collectDragAlternatives
} from './diagnostics';
import { installRectHarness, installViewportHarness } from './domHarness';
import { first } from './testUtil';

let restore: () => void;
let restoreViewport: () => void;
beforeEach(() => { restore = installRectHarness(); restoreViewport = installViewportHarness(320, 640); });
afterEach(() => {
  restoreViewport();
  restore();
  document.body.innerHTML = '';
  document.getElementById('__wcag1412__')?.remove();
  document.getElementById('__wcag1412svg__')?.remove();
});

describe('collectProvenance', () => {
  it('records the fields a reviewer needs to reproduce a run', () => {
    const p = collectProvenance();
    expect(typeof p.timestamp).toBe('string');
    expect(typeof p.innerWidth).toBe('number');
    expect(typeof p.devicePixelRatio).toBe('number');
    expect(['light', 'dark']).toContain(p.colorScheme);
    expect(typeof p.hasTouch).toBe('boolean');
    expect(typeof p.userAgent).toBe('string');
  });
  it('reports an unset document language explicitly rather than as an empty string', () => {
    document.documentElement.lang = '';
    expect(collectProvenance().documentLang).toBe('(unset)');
  });
  it('reports a set language', () => {
    document.documentElement.lang = 'en-GB';
    expect(collectProvenance().documentLang).toBe('en-GB');
    document.documentElement.lang = '';
  });
});

describe('collectReflow', () => {
  it('excepts the map canvas itself but NOT the MapLibre controls inside the map', () => {
    document.body.innerHTML = `
      <div class="maplibregl-map">
        <div class="maplibregl-canvas-container" data-rect="0,0,2000,400">
          <canvas class="maplibregl-canvas" data-rect="0,0,2000,400"></canvas></div>
        <div class="maplibregl-ctrl-group" data-rect="0,0,2000,44">
          <button data-rect="0,0,2000,44">Zoom in</button></div>
      </div>`;
    const r = collectReflow();
    const tags = r.candidates.map(c => c.tag);
    expect(tags).not.toContain('canvas');
    expect(tags).toContain('button');            // controls are ordinary content
  });
  it('detects left-edge overflow, not only right', () => {
    document.body.innerHTML = `<div data-rect="-50,0,20,20">off to the left</div>`;
    expect(first(collectReflow().candidates).side).toBe('left');
  });
  it('reports content in an intentional scroll region separately rather than dropping it', () => {
    document.body.innerHTML = `
      <div style="overflow-x:auto" data-rect="0,0,300,100">
        <div data-rect="0,0,2000,100">wide</div></div>`;
    const r = collectReflow();
    expect(r.inScrollRegions.length).toBeGreaterThan(0);
    expect(r.candidates.map(c => c.tag)).not.toContain('div');
  });
  it('flags a clipped table cell — tables are excepted, individual cells are not', () => {
    document.body.innerHTML = `<table><tr><td style="overflow:hidden" data-rect="0,0,40,20">x</td></tr></table>`;
    const cell = document.querySelector('td');
    if (cell) {
      Object.defineProperty(cell, 'clientWidth', { value: 40, configurable: true });
      Object.defineProperty(cell, 'scrollWidth', { value: 200, configurable: true });
    }
    expect(collectReflow().clippedTableCells).toHaveLength(1);
  });
  it('reports when root overflow is suppressed, since clipping then reads as a pass', () => {
    document.documentElement.style.overflowX = 'hidden';
    expect(collectReflow().rootOverflowSuppressed).toBe(true);
    document.documentElement.style.overflowX = '';
  });
  it('produces no candidates for a clean narrow layout', () => {
    document.body.innerHTML = `<div data-rect="0,0,100,100">fine</div>`;
    expect(collectReflow().candidates).toHaveLength(0);
  });
});

describe('text spacing diagnostics', () => {
  it('injects the four WCAG 1.4.12 values and removes them on a second call', () => {
    const applied = toggleDomTextSpacing();
    expect(applied.applied).toBe(true);
    const style = document.getElementById('__wcag1412__');
    expect(style?.textContent).toContain('line-height: 1.5');
    expect(style?.textContent).toContain('letter-spacing: 0.12em');
    expect(style?.textContent).toContain('word-spacing: 0.16em');
    expect(style?.textContent).toContain('margin-bottom: 2em');
    expect(toggleDomTextSpacing().applied).toBe(false);
    expect(document.getElementById('__wcag1412__')).toBeNull();
  });
  it('applies letter and word spacing to SVG text, which is real text', () => {
    document.body.innerHTML = `<svg><text>1994</text></svg>`;
    const r = toggleSvgTextSpacing();
    expect(r.applied).toBe(true);
    expect(r.svgTextCount).toBe(1);
    const style = document.getElementById('__wcag1412svg__');
    expect(style?.textContent).toContain('svg text');
    expect(style?.textContent).not.toContain('line-height');   // does not apply to SVG <text>
    toggleSvgTextSpacing();
  });
  it('the two toggles are independent', () => {
    toggleDomTextSpacing();
    expect(document.getElementById('__wcag1412svg__')).toBeNull();
    toggleDomTextSpacing();
  });
});

describe('collectDragAlternatives', () => {
  it('reports no declared pan control as a candidate, not a verdict', () => {
    document.body.innerHTML = `<div class="maplibregl-canvas-container"></div>`;
    const r = collectDragAlternatives();
    expect(r.declaredPanControls).toHaveLength(0);
    expect(r.status).toContain('candidate requiring functional-equivalence');
  });
  it('reads the explicit data-map-pan contract', () => {
    document.body.innerHTML = `
      <button data-map-pan="north" aria-label="Pan north" data-rect="0,0,44,44"></button>
      <button data-map-pan="south" aria-label="Pan south" data-rect="0,50,44,44"></button>`;
    const r = collectDragAlternatives();
    expect(r.declaredPanControls.map(p => p.direction)).toEqual(['north', 'south']);
    expect(r.status).toContain('assert behaviour');
  });
  it('does not match unrelated labels — "Download" once matched a "down" regex', () => {
    document.body.innerHTML = `<button aria-label="Download records" data-rect="0,0,44,44"></button>
                               <button aria-label="Remove filter" data-rect="0,50,44,44"></button>`;
    expect(collectDragAlternatives().declaredPanControls).toHaveLength(0);
  });
  it('flags title/aria-label double-speak on map controls', () => {
    document.body.innerHTML = `<div class="maplibregl-ctrl-group">
      <button aria-label="Zoom in" title="Zoom in" data-rect="0,0,44,44"></button></div>`;
    expect(first(collectDragAlternatives().controlButtons).doubleSpeak).toBe(true);
  });
  it('does not flag double-speak when only aria-label is set', () => {
    document.body.innerHTML = `<div class="maplibregl-ctrl-group">
      <button aria-label="Zoom in" data-rect="0,0,44,44"></button></div>`;
    expect(first(collectDragAlternatives().controlButtons).doubleSpeak).toBe(false);
  });
  it('reports cooperative gestures and canvas ARIA state', () => {
    document.body.innerHTML = `
      <div class="maplibregl-canvas-container maplibregl-cooperative-gestures">
        <canvas class="maplibregl-canvas" tabindex="0" role="region" aria-label="Map"></canvas></div>`;
    const r = collectDragAlternatives();
    expect(r.cooperativeGesturesActive).toBe(true);
    expect(r.canvasTabIndex).toBe('0');
    expect(r.canvasRole).toBe('region');
    expect(r.canvasAriaLabel).toBe('Map');
  });
});

describe('collectReflow — predicate boundaries', () => {
  it('ignores overflow of exactly 1px but reports 2px', () => {
    document.body.innerHTML = `<div data-rect="0,0,321,20">one</div>`;
    expect(collectReflow().candidates).toHaveLength(0);
    document.body.innerHTML = `<div data-rect="0,0,322,20">two</div>`;
    expect(collectReflow().candidates).toHaveLength(1);
  });
  it('labels equal left and right overflow as "right"', () => {
    // left overflow 10, right overflow 10 (viewport 320): the tie resolves to right.
    document.body.innerHTML = `<div data-rect="-10,0,340,20">both</div>`;
    expect(first(collectReflow().candidates).side).toBe('right');
  });
  it('skips a display:none element even when it overflows', () => {
    document.body.innerHTML = `<div style="display:none" data-rect="0,0,2000,20">x</div>`;
    expect(collectReflow().candidates).toHaveLength(0);
  });
  it('skips a visibility:hidden element even when it overflows', () => {
    document.body.innerHTML = `<div style="visibility:hidden" data-rect="0,0,2000,20">x</div>`;
    expect(collectReflow().candidates).toHaveLength(0);
  });
  it.each([
    ['overflow', 'overflow:hidden'],
    ['overflow-x', 'overflow-x:hidden'],
    ['overflow-y', 'overflow-y:hidden'],
    ['text-overflow', 'text-overflow:ellipsis']
  ])('detects a clipped cell via %s', (_l, style) => {
    document.body.innerHTML = `<table><tr><td style="${style}" data-rect="0,0,40,20">x</td></tr></table>`;
    const cell = document.querySelector('td');
    if (cell) {
      Object.defineProperty(cell, 'clientWidth', { value: 40, configurable: true });
      Object.defineProperty(cell, 'scrollWidth', { value: 200, configurable: true });
    }
    expect(collectReflow().clippedTableCells).toHaveLength(1);
  });
  it('does not flag a cell that clips nothing', () => {
    document.body.innerHTML = `<table><tr><td style="overflow:hidden" data-rect="0,0,40,20">x</td></tr></table>`;
    const cell = document.querySelector('td');
    if (cell) {
      Object.defineProperty(cell, 'clientWidth', { value: 200, configurable: true });
      Object.defineProperty(cell, 'scrollWidth', { value: 200, configurable: true });
    }
    expect(collectReflow().clippedTableCells).toHaveLength(0);
  });
  it('does not flag an overflowing cell that is not clipped', () => {
    document.body.innerHTML = `<table><tr><td data-rect="0,0,40,20">x</td></tr></table>`;
    const cell = document.querySelector('td');
    if (cell) {
      Object.defineProperty(cell, 'clientWidth', { value: 40, configurable: true });
      Object.defineProperty(cell, 'scrollWidth', { value: 200, configurable: true });
    }
    expect(collectReflow().clippedTableCells).toHaveLength(0);
  });
});

describe('collectDragAlternatives — double-speak boundaries', () => {
  it('is false when title is empty and aria-label is empty', () => {
    document.body.innerHTML = `<div class="maplibregl-ctrl-group">
      <button title="" data-rect="0,0,44,44"></button></div>`;
    expect(first(collectDragAlternatives().controlButtons).doubleSpeak).toBe(false);
  });
  it('is false when title and aria-label differ', () => {
    document.body.innerHTML = `<div class="maplibregl-ctrl-group">
      <button title="Zoom in" aria-label="Increase zoom" data-rect="0,0,44,44"></button></div>`;
    expect(first(collectDragAlternatives().controlButtons).doubleSpeak).toBe(false);
  });
  it('is false when only title is set', () => {
    document.body.innerHTML = `<div class="maplibregl-ctrl-group">
      <button title="Zoom in" data-rect="0,0,44,44"></button></div>`;
    expect(first(collectDragAlternatives().controlButtons).doubleSpeak).toBe(false);
  });
});

describe('collectProvenance — touch detection', () => {
  const setTouchPoints = (n: number): void => {
    Object.defineProperty(navigator, 'maxTouchPoints', { value: n, configurable: true });
  };
  afterEach(() => { setTouchPoints(0); });

  it('reports touch from maxTouchPoints even without an ontouchstart property', () => {
    setTouchPoints(5);
    expect(collectProvenance().hasTouch).toBe(true);
    expect(collectProvenance().touchPoints).toBe(5);
  });
  it('reports no touch on a pointer-only device', () => {
    setTouchPoints(0);
    expect(collectProvenance().hasTouch).toBe(false);
  });
});

describe('collectReflow — element filtering edge cases', () => {
  it('processes a zero-width element that overflows to the left', () => {
    document.body.innerHTML = `<div data-rect="-50,0,0,20">sliver</div>`;
    expect(collectReflow().candidates).toHaveLength(1);
  });
  it('skips an element with no area at all', () => {
    document.body.innerHTML = `<div data-rect="-50,0,0,0">nothing</div>`;
    expect(collectReflow().candidates).toHaveLength(0);
  });
  it('reads an SVG class name via baseVal rather than printing an object', () => {
    document.body.innerHTML = `<svg class="chart"><rect class="bar" data-rect="0,0,2000,20"></rect></svg>`;
    const bar = collectReflow().candidates.find(c => c.tag === 'rect');
    expect(bar?.cls).toBe('bar');
  });
  it('skips a display:none table cell that would otherwise look clipped', () => {
    document.body.innerHTML =
      `<table><tr><td style="display:none;overflow:hidden" data-rect="0,0,40,20">x</td></tr></table>`;
    const cell = document.querySelector('td');
    if (cell) {
      Object.defineProperty(cell, 'clientWidth', { value: 40, configurable: true });
      Object.defineProperty(cell, 'scrollWidth', { value: 200, configurable: true });
    }
    expect(collectReflow().clippedTableCells).toHaveLength(0);
  });
  it('skips a visibility:hidden table cell', () => {
    document.body.innerHTML =
      `<table><tr><td style="visibility:hidden;overflow:hidden" data-rect="0,0,40,20">x</td></tr></table>`;
    const cell = document.querySelector('td');
    if (cell) {
      Object.defineProperty(cell, 'clientWidth', { value: 40, configurable: true });
      Object.defineProperty(cell, 'scrollWidth', { value: 200, configurable: true });
    }
    expect(collectReflow().clippedTableCells).toHaveLength(0);
  });
});

describe('toggleDomTextSpacing — clipping detection axes', () => {
  const stub = (el: Element, o: { cw?: number; sw?: number; ch?: number; sh?: number }): void => {
    for (const [k, v] of Object.entries({
      clientWidth: o.cw ?? 100, scrollWidth: o.sw ?? 100,
      clientHeight: o.ch ?? 20, scrollHeight: o.sh ?? 20
    })) Object.defineProperty(el, k, { value: v, configurable: true });
  };
  it('detects vertical clipping alone', () => {
    document.body.innerHTML = `<div id="t" style="overflow-y:hidden">text</div>`;
    const el = document.getElementById('t');
    if (el) stub(el, { ch: 20, sh: 200 });
    const r = toggleDomTextSpacing();
    expect(r.clippedCandidates.some(c => c.clippedVertically && !c.clippedHorizontally)).toBe(true);
    toggleDomTextSpacing();
  });
  it('detects horizontal clipping alone', () => {
    document.body.innerHTML = `<div id="t" style="overflow-x:hidden">text</div>`;
    const el = document.getElementById('t');
    if (el) stub(el, { cw: 40, sw: 400 });
    const r = toggleDomTextSpacing();
    expect(r.clippedCandidates.some(c => c.clippedHorizontally && !c.clippedVertically)).toBe(true);
    toggleDomTextSpacing();
  });
  it('accepts overflow:clip as well as hidden', () => {
    document.body.innerHTML = `<div id="t" style="overflow-y:clip">text</div>`;
    const el = document.getElementById('t');
    if (el) stub(el, { ch: 20, sh: 200 });
    expect(toggleDomTextSpacing().clippedCandidates.length).toBeGreaterThan(0);
    toggleDomTextSpacing();
  });
  it('ignores an overflowing element that is not clipped', () => {
    document.body.innerHTML = `<div id="t">text</div>`;
    const el = document.getElementById('t');
    if (el) stub(el, { ch: 20, sh: 200 });
    expect(toggleDomTextSpacing().clippedCandidates).toHaveLength(0);
    toggleDomTextSpacing();
  });
  it('skips a display:none element', () => {
    document.body.innerHTML = `<div id="t" style="display:none;overflow-y:hidden">text</div>`;
    const el = document.getElementById('t');
    if (el) stub(el, { ch: 20, sh: 200 });
    expect(toggleDomTextSpacing().clippedCandidates).toHaveLength(0);
    toggleDomTextSpacing();
  });
});

describe('toggleSvgTextSpacing — escape directions', () => {
  const svgWith = (textRect: string, svgRect: string): void => {
    document.body.innerHTML = `<svg data-rect="${svgRect}"><text data-rect="${textRect}">1994</text></svg>`;
  };
  it('detects a label escaping to the right only', () => {
    svgWith('0,0,300,20', '0,0,200,100');
    const r = toggleSvgTextSpacing();
    expect(r.escaping.some(e => e.escapesRight && !e.escapesLeft)).toBe(true);
    toggleSvgTextSpacing();
  });
  it('detects a label escaping to the left only', () => {
    svgWith('-50,0,40,20', '0,0,200,100');
    const r = toggleSvgTextSpacing();
    expect(r.escaping.some(e => e.escapesLeft && !e.escapesRight)).toBe(true);
    toggleSvgTextSpacing();
  });
  it('does not flag a label inside its SVG', () => {
    svgWith('10,0,40,20', '0,0,200,100');
    expect(toggleSvgTextSpacing().escaping).toHaveLength(0);
    toggleSvgTextSpacing();
  });
});
