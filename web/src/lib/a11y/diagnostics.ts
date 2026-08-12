/**
 * Browser-side diagnostic collectors, committed as code rather than copied between
 * protocol documents. Each is SELF-CONTAINED (no module-scope references) so it can be
 * handed to page.evaluate(); each returns plain data for assertion in Node.
 *
 * These replace the "Script P / R / S / S2 / M" snippets that earlier protocol versions
 * pasted into markdown — where they drifted between versions and could not be tested.
 */

/* ── Provenance ─────────────────────────────────────────────────────────────── */

export interface Provenance {
  url: string; timestamp: string;
  innerWidth: number; innerHeight: number; devicePixelRatio: number;
  colorScheme: 'dark' | 'light';
  reducedMotion: boolean; forcedColors: boolean;
  touchPoints: number; hasTouch: boolean;
  documentLang: string; title: string; userAgent: string;
}

export function collectProvenance(): Provenance {
  return {
    url: location.href,
    timestamp: new Date().toISOString(),
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    devicePixelRatio: window.devicePixelRatio,
    colorScheme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
    reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
    forcedColors: matchMedia('(forced-colors: active)').matches,
    touchPoints: navigator.maxTouchPoints,
    // `'ontouchstart' in window` is unreliable: engines expose the event-handler
    // property whether or not the device has a touchscreen. maxTouchPoints plus the
    // any-pointer media query is the accurate test.
    hasTouch: navigator.maxTouchPoints > 0 || matchMedia('(any-pointer: coarse)').matches,
    documentLang: document.documentElement.lang === '' ? '(unset)' : document.documentElement.lang,
    title: document.title,
    userAgent: navigator.userAgent
  };
}

/* ── Reflow (SC 1.4.10) ─────────────────────────────────────────────────────── */

export interface OverflowCandidate {
  tag: string; cls: string; side: 'left' | 'right'; overflowPx: number;
}
export interface ClippedCell { text: string; clientWidth: number; scrollWidth: number }
export interface ReflowReport {
  innerWidth: number; clientWidth: number; scrollWidth: number;
  rootHorizontalScroll: boolean;
  /** No scrollbar appears, but content may be CLIPPED — worse, and reads as a pass. */
  rootOverflowSuppressed: boolean;
  candidates: OverflowCandidate[];
  /** Reported, not discarded: an intentional scroll region is a judgement call. */
  inScrollRegions: OverflowCandidate[];
  /** Reflow Note 2 excepts data tables but NOT individual cells. */
  clippedTableCells: ClippedCell[];
  note: string;
}

export function collectReflow(): ReflowReport {
  const d = document.documentElement;
  const vw = d.clientWidth;
  const suppressed = (s: string): boolean => s === 'hidden' || s === 'clip';
  const rootOverflowSuppressed =
    suppressed(getComputedStyle(d).overflowX) || suppressed(getComputedStyle(document.body).overflowX);

  // matches(), never closest(): a descendant of an excepted element (MapLibre controls,
  // the cooperative-gesture overlay) is NOT itself excepted.
  const EXCEPTED = '.maplibregl-canvas, .maplibregl-canvas-container, [data-reflow-exception]';

  const clsOf = (el: Element): string => {
    const c: unknown = el.className;
    if (typeof c === 'string') return c.slice(0, 50);
    if (c !== null && typeof c === 'object' && 'baseVal' in c) {
      const b = (c as { baseVal: unknown }).baseVal;
      return typeof b === 'string' ? b.slice(0, 50) : '';
    }
    return '';
  };
  const inScrollContainer = (el: Element): boolean => {
    let p: Element | null = el.parentElement;
    while (p !== null && p !== d) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
      p = p.parentElement;
    }
    return false;
  };

  const candidates: OverflowCandidate[] = [];
  const inScrollRegions: OverflowCandidate[] = [];
  const all = document.querySelectorAll('body *');
  for (let i = 0; i < all.length; i++) {
    const el = all.item(i);
    if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const overRight = r.right - vw;
    const overLeft = -r.left;
    const over = Math.max(overRight, overLeft);
    if (over <= 1) continue;
    if (el.matches(EXCEPTED)) continue;
    const entry: OverflowCandidate = {
      tag: el.tagName.toLowerCase(), cls: clsOf(el),
      side: overRight >= overLeft ? 'right' : 'left',
      overflowPx: Math.round(over)
    };
    if (inScrollContainer(el)) inScrollRegions.push(entry);
    else candidates.push(entry);
  }

  const clippedTableCells: ClippedCell[] = [];
  const cellNodes = document.querySelectorAll('td, th');
  for (let i = 0; i < cellNodes.length; i++) {
    const cell = cellNodes.item(i);
    if (!cell) continue;
    const cs = getComputedStyle(cell);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const hides = suppressed(cs.overflow) || suppressed(cs.overflowX) ||
                  suppressed(cs.overflowY) || cs.textOverflow === 'ellipsis';
    const overflows = cell.scrollWidth > cell.clientWidth + 1 || cell.scrollHeight > cell.clientHeight + 1;
    if (hides && overflows) {
      clippedTableCells.push({
        text: (cell.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40),
        clientWidth: Math.round(cell.clientWidth),
        scrollWidth: Math.round(cell.scrollWidth)
      });
    }
  }

  candidates.sort((a, b) => b.overflowPx - a.overflowPx);
  return {
    innerWidth: window.innerWidth, clientWidth: vw, scrollWidth: d.scrollWidth,
    rootHorizontalScroll: d.scrollWidth > vw + 1,
    rootOverflowSuppressed,
    candidates: candidates.slice(0, 25),
    inScrollRegions: inScrollRegions.slice(0, 25),
    clippedTableCells: clippedTableCells.slice(0, 25),
    note: 'Candidates require human classification: excepted section / intentional scroll / defect.'
  };
}

/* ── Text spacing (SC 1.4.12) ───────────────────────────────────────────────── */

export interface SpacingClip {
  tag: string; cls: string; text: string;
  clippedVertically: boolean; clippedHorizontally: boolean;
}
export interface TextSpacingReport { applied: boolean; clippedCandidates: SpacingClip[]; note: string }

/** Toggles: first call injects the WCAG values, second removes them. */
export function toggleDomTextSpacing(): TextSpacingReport {
  const ID = '__wcag1412__';
  const existing = document.getElementById(ID);
  if (existing) {
    existing.remove();
    return { applied: false, clippedCandidates: [], note: 'Injected style removed.' };
  }
  const style = document.createElement('style');
  style.id = ID;
  style.textContent =
    '*:not(svg):not(svg *):not(canvas) { line-height: 1.5 !important;' +
    ' letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }' +
    'p { margin-bottom: 2em !important; }';
  document.head.appendChild(style);
  void document.documentElement.offsetHeight;

  const clsOf = (el: Element): string => (typeof el.className === 'string' ? el.className.slice(0, 50) : '');
  const clipped: SpacingClip[] = [];
  const all = document.querySelectorAll('body *');
  for (let i = 0; i < all.length; i++) {
    const el = all.item(i);
    if (!el || el.closest('svg, canvas')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const hidesY = cs.overflowY === 'hidden' || cs.overflowY === 'clip';
    const hidesX = cs.overflowX === 'hidden' || cs.overflowX === 'clip';
    const overY = el.scrollHeight > el.clientHeight + 1;
    const overX = el.scrollWidth > el.clientWidth + 1;
    if ((hidesY && overY) || (hidesX && overX)) {
      clipped.push({
        tag: el.tagName.toLowerCase(), cls: clsOf(el),
        text: (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40),
        clippedVertically: hidesY && overY, clippedHorizontally: hidesX && overX
      });
    }
  }
  return {
    applied: true, clippedCandidates: clipped.slice(0, 25),
    note: 'Screenshot and compare; bounding-box checks do not detect overlap. ' +
          'SVG excluded — run toggleSvgTextSpacing for Recharts labels. Re-run to remove.'
  };
}

export interface SvgSpacingIssue {
  text: string; widthBefore: number | null; widthAfter: number | null;
  escapesLeft: boolean; escapesRight: boolean;
}
export interface SvgSpacingReport { applied: boolean; svgTextCount: number; escaping: SvgSpacingIssue[]; note: string }

/** SVG text is real text and is in scope for 1.4.12; canvas text is images-of-text. */
export function toggleSvgTextSpacing(): SvgSpacingReport {
  const ID = '__wcag1412svg__';
  const existing = document.getElementById(ID);
  if (existing) {
    existing.remove();
    return { applied: false, svgTextCount: 0, escaping: [], note: 'SVG spacing style removed.' };
  }
  const widthOf = (t: SVGGraphicsElement): number | null => {
    try { return t.getBBox().width; } catch { return null; }
  };
  const nodes = Array.from(document.querySelectorAll('svg text')) as SVGGraphicsElement[];
  const before = nodes.map(t => ({ t, w: widthOf(t) }));

  const style = document.createElement('style');
  style.id = ID;
  // line-height does not apply to SVG <text>; letter and word spacing do.
  style.textContent = 'svg text { letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }';
  document.head.appendChild(style);
  void document.documentElement.offsetHeight;

  const escaping: SvgSpacingIssue[] = [];
  for (const { t, w } of before) {
    const svg = t.ownerSVGElement;
    if (!svg) continue;
    const sb = svg.getBoundingClientRect();
    const r = t.getBoundingClientRect();
    const escapesLeft = r.left < sb.left - 1;
    const escapesRight = r.right > sb.right + 1;
    if (escapesLeft || escapesRight) {
      escaping.push({
        text: (t.textContent ?? '').trim().slice(0, 30),
        widthBefore: w, widthAfter: widthOf(t), escapesLeft, escapesRight
      });
    }
  }
  return {
    applied: true, svgTextCount: before.length, escaping: escaping.slice(0, 25),
    note: 'Bounds checks miss label collision — compare screenshots. Re-run to remove.'
  };
}

/* ── Map drag alternatives (SC 2.5.7 / 2.5.1) ───────────────────────────────── */

export interface MapControlInfo {
  ariaLabel: string | null; title: string | null;
  doubleSpeak: boolean; width: number; height: number;
}
export interface DragAlternativeReport {
  canvasTouchAction: string | null; canvasTabIndex: string | null;
  canvasRole: string | null; canvasAriaLabel: string | null;
  containerClasses: string | null; cooperativeGesturesActive: boolean | null;
  controlButtons: MapControlInfo[];
  declaredPanControls: { direction: string; name: string }[];
  status: string; note: string;
}

export function collectDragAlternatives(): DragAlternativeReport {
  const canvas = document.querySelector('.maplibregl-canvas');
  const cont = document.querySelector('.maplibregl-canvas-container');

  const controlButtons: MapControlInfo[] = [];
  const btns = document.querySelectorAll('.maplibregl-ctrl-group button');
  for (let i = 0; i < btns.length; i++) {
    const b = btns.item(i);
    if (!(b instanceof HTMLElement)) continue;
    const r = b.getBoundingClientRect();
    const aria = b.getAttribute('aria-label');
    const title = b.getAttribute('title');
    controlButtons.push({
      ariaLabel: aria, title,
      doubleSpeak: title !== null && title !== '' && title === aria,
      width: Math.round(r.width * 10) / 10, height: Math.round(r.height * 10) / 10
    });
  }

  // Explicit contract only. Earlier versions used a label regex, which matched
  // "Download" for "down" and "Remove" for "move"; presence was never evidence anyway.
  const declared: { direction: string; name: string }[] = [];
  const panNodes = document.querySelectorAll('[data-map-pan]');
  for (let i = 0; i < panNodes.length; i++) {
    const b = panNodes.item(i);
    if (!b) continue;
    declared.push({
      direction: b.getAttribute('data-map-pan') ?? '',
      name: (b.getAttribute('aria-label') ?? b.textContent ?? '').trim().slice(0, 40)
    });
  }

  return {
    canvasTouchAction: canvas ? getComputedStyle(canvas).touchAction : null,
    canvasTabIndex: canvas ? canvas.getAttribute('tabindex') : null,
    canvasRole: canvas ? canvas.getAttribute('role') : null,
    canvasAriaLabel: canvas ? canvas.getAttribute('aria-label') : null,
    containerClasses: cont ? cont.className : null,
    cooperativeGesturesActive: cont ? cont.classList.contains('maplibregl-cooperative-gestures') : null,
    controlButtons,
    declaredPanControls: declared,
    status: declared.length > 0
      ? 'Declared pan controls present — assert behaviour, not presence'
      : 'No declared pan control — candidate requiring functional-equivalence assessment (SC 2.5.7)',
    note: 'WCAG permits any separate non-dragging component achieving the same result. ' +
          'Presence is not conformance; absence is not automatically non-conformance.'
  };
}
