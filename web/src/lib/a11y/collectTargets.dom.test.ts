import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { collectTargets } from './collectTargets';
import { installRectHarness } from './domHarness';
import { first } from './testUtil';

let restore: () => void;
beforeEach(() => { restore = installRectHarness(); });
afterEach(() => { restore(); document.body.innerHTML = ''; });

const render = (html: string): void => { document.body.innerHTML = html; };
const byLabel = (label: string) => collectTargets().find(t => t.label === label);

describe('collectTargets — selection', () => {
  it('collects buttons, links and inputs', () => {
    render(`<button data-rect="0,0,44,44">Zoom in</button>
            <a href="#x" data-rect="60,0,44,44">Records</a>
            <input data-rect="120,0,44,44" aria-label="Year">`);
    expect(collectTargets().map(t => t.label).sort()).toEqual(['Records', 'Year', 'Zoom in']);
  });
  it('collects Recharts cells marked with data-a11y-pointer-target', () => {
    render(`<svg><path data-a11y-pointer-target="chart-bar-1994" data-rect="0,0,16,50"
                       aria-label="1994: 12 records"></path></svg>`);
    expect(byLabel('1994: 12 records')).toBeDefined();
  });
  it('skips display:none, visibility:hidden and pointer-events:none', () => {
    render(`<button style="display:none" data-rect="0,0,44,44">A</button>
            <button style="visibility:hidden" data-rect="0,0,44,44">B</button>
            <button style="pointer-events:none" data-rect="0,0,44,44">C</button>
            <button data-rect="0,0,44,44">D</button>`);
    expect(collectTargets().map(t => t.label)).toEqual(['D']);
  });
  it('skips zero-area elements', () => {
    render(`<button data-rect="0,0,0,44">A</button><button data-rect="0,0,44,44">B</button>`);
    expect(collectTargets().map(t => t.label)).toEqual(['B']);
  });
  it('skips tabindex="-1"', () => {
    render(`<div tabindex="-1" data-rect="0,0,44,44">A</div><div tabindex="0" data-rect="0,0,44,44">B</div>`);
    expect(collectTargets().map(t => t.label)).toEqual(['B']);
  });
  it('skips focusable scroll regions explicitly marked as non-pointer targets', () => {
    render(`<div tabindex="0" data-a11y-non-pointer-target data-rect="0,0,200,100">Scrollable table</div>
            <button data-rect="0,120,44,44">A</button>`);
    expect(collectTargets().map(t => t.label)).toEqual(['A']);
  });
  it('skips controls inside closed details while retaining its summary', () => {
    render(`<details>
              <summary data-rect="0,0,120,44">Yearly figures</summary>
              <button data-rect="0,50,44,44">1995</button>
            </details>`);
    expect(collectTargets().map(t => t.label)).toEqual(['Yearly figures']);
  });
  it('collects controls inside open details', () => {
    render(`<details open>
              <summary data-rect="0,0,120,44">Yearly figures</summary>
              <button data-rect="0,50,44,44">1995</button>
            </details>`);
    expect(collectTargets().map(t => t.label)).toEqual(['Yearly figures', '1995']);
  });
  it('assigns contiguous indexes starting at zero', () => {
    render(`<button data-rect="0,0,44,44">A</button>
            <button style="display:none" data-rect="0,0,44,44">skipped</button>
            <button data-rect="60,0,44,44">B</button>`);
    expect(collectTargets().map(t => t.index)).toEqual([0, 1]);
  });
  it('falls back to a tag-based label when there is no accessible name', () => {
    render(`<button data-rect="0,0,44,44"></button>`);
    expect(first(collectTargets()).label).toBe('button#0');
  });
  it('prefers aria-label over text content', () => {
    render(`<button aria-label="Zoom in" data-rect="0,0,44,44">+</button>`);
    expect(first(collectTargets()).label).toBe('Zoom in');
  });
});

describe('collectTargets — geometry confidence', () => {
  it('marks a plain rectangle verified', () => {
    render(`<button data-rect="0,0,44,44">A</button>`);
    expect(first(collectTargets()).geometryConfidence).toBe('verified-rectangular');
  });
  it('marks a rounded control unverified', () => {
    render(`<button style="border-radius:50%" data-rect="0,0,24,24">A</button>`);
    expect(first(collectTargets()).geometryConfidence).toBe('unverified');
  });
  it('marks a clip-path control unverified', () => {
    render(`<button style="clip-path:circle(50%)" data-rect="0,0,44,44">A</button>`);
    expect(first(collectTargets()).geometryConfidence).toBe('unverified');
  });
  it.each([
    ['rotation', 'matrix(0.94, 0.34, -0.34, 0.94, 0, 0)'],
    ['skewX', 'matrix(1, 0, 0.5, 1, 0, 0)'],
    ['skewY', 'matrix(1, 0.5, 0, 1, 0, 0)'],
    ['horizontal flip', 'matrix(-1, 0, 0, 1, 0, 0)'],
    ['vertical flip', 'matrix(1, 0, 0, -1, 0, 0)']
  ])('marks %s unverified', (_l, transform) => {
    render(`<button style="transform:${transform}" data-rect="0,0,44,44">A</button>`);
    expect(first(collectTargets()).geometryConfidence).toBe('unverified');
  });
  it('treats a pure translation as still rectangular', () => {
    render(`<button style="transform:matrix(1, 0, 0, 1, 10, 10)" data-rect="0,0,44,44">A</button>`);
    expect(first(collectTargets()).geometryConfidence).toBe('verified-rectangular');
  });
  it('marks a non-rect SVG shape unverified', () => {
    render(`<svg><circle data-a11y-pointer-target="c" data-rect="0,0,44,44" aria-label="C"></circle></svg>`);
    expect(byLabel('C')?.geometryConfidence).toBe('unverified');
  });
  it('marks a target clipped by an ancestor unverified', () => {
    render(`<div style="overflow:hidden" data-rect="0,0,20,44">
              <button data-rect="0,0,44,44">A</button></div>`);
    expect(byLabel('A')?.geometryConfidence).toBe('unverified');
  });
  it('does not penalise a target fully inside a clipping ancestor', () => {
    render(`<div style="overflow:hidden" data-rect="0,0,200,200">
              <button data-rect="10,10,44,44">A</button></div>`);
    expect(byLabel('A')?.geometryConfidence).toBe('verified-rectangular');
  });
});

describe('collectTargets — claims and groups', () => {
  it('reads an exception claim from the element itself', () => {
    render(`<button data-a11y-target-exception="essential" data-rect="0,0,16,16">A</button>`);
    expect(first(collectTargets()).exceptionClaim).toBe('essential');
  });
  it('does NOT inherit a claim from a wrapper — closest() would have exempted the controls inside', () => {
    render(`<div data-a11y-target-exception="essential">
              <button data-rect="0,0,16,16">Zoom in</button></div>`);
    expect(byLabel('Zoom in')?.exceptionClaim).toBeNull();
  });
  it('reads a same-action group', () => {
    render(`<button data-a11y-same-action="zoom" data-rect="0,0,44,44">A</button>`);
    expect(first(collectTargets()).sameActionGroup).toBe('zoom');
  });
  it('reports a null claim when the attribute is absent', () => {
    render(`<button data-rect="0,0,44,44">A</button>`);
    expect(first(collectTargets()).exceptionClaim).toBeNull();
    expect(first(collectTargets()).sameActionGroup).toBeNull();
  });
});

describe('collectTargets — rect fidelity', () => {
  it('reports the rect verbatim, without rounding', () => {
    render(`<button data-rect="1.5,2.25,23.96,44.5">A</button>`);
    const t = first(collectTargets());
    expect(t.rect.width).toBeCloseTo(23.96, 6);
    expect(t.rect.right).toBeCloseTo(25.46, 6);
    expect(t.rect.bottom).toBeCloseTo(46.75, 6);
  });
});

describe('collectTargets — filter and clipping boundaries', () => {
  it('skips a zero-height element as well as a zero-width one', () => {
    render(`<button data-rect="0,0,44,0">A</button><button data-rect="0,0,44,44">B</button>`);
    expect(collectTargets().map(t => t.label)).toEqual(['B']);
  });
  it.each([
    ['overflow-x hidden', 'overflow-x:hidden'],
    ['overflow-y hidden', 'overflow-y:hidden'],
    ['overflow hidden', 'overflow:hidden'],
    ['overflow clip', 'overflow:clip'],
    ['clip-path', 'clip-path:inset(0)']
  ])('treats %s on an ancestor as clipping', (_l, style) => {
    render(`<div style="${style}" data-rect="0,0,20,20"><button data-rect="0,0,44,44">A</button></div>`);
    expect(byLabel('A')?.geometryConfidence).toBe('unverified');
  });
  it.each([
    ['left', '-10,0,44,44'],
    ['right', '0,0,300,44'],
    ['top', '0,-10,44,44'],
    ['bottom', '0,0,44,300']
  ])('detects a target escaping its clipping ancestor on the %s edge', (_l, r) => {
    render(`<div style="overflow:hidden" data-rect="0,0,100,100">
              <button data-rect="${r}">A</button></div>`);
    expect(byLabel('A')?.geometryConfidence).toBe('unverified');
  });
});
