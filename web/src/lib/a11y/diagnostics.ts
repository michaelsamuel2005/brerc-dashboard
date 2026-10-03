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
export interface TextSpacingReport {
  applied: boolean;
  /** Elements clipped BY the spacing override. Capped for reporting; see clippedTotal. */
  clippedCandidates: SpacingClip[];
  /** How many were found in total, so the cap above can never read as "that was all". */
  clippedTotal: number;
  /** How many were already clipped before the override — not a 1.4.12 failure. */
  preexistingClips: number;
  note: string;
}

/**
 * Toggles: first call injects the WCAG values, second removes them.
 *
 * SC 1.4.12 asks whether SETTING the text spacing causes a loss of content — not whether
 * any clipping exists. So this measures each element twice, before and after, and reports
 * only elements that were fine before and are clipped after.
 *
 * That distinction is not academic. The standard visually-hidden pattern
 * (`width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0)`) is a permanently clipped
 * box by construction — that is how screen-reader-only text is written. Measuring after
 * the override alone reported every such string as a text-spacing failure, so this
 * diagnostic failed on any page with accessible hidden labels and could never pass. It
 * had blocked the accessibility gate on every viewport since the suite was written.
 *
 * Elements clipped in BOTH passes are still counted, in `preexistingClips`, so nothing is
 * hidden — they are simply not attributed to text spacing.
 *
 * Self-contained by requirement: Playwright serialises only this function's source into
 * the page, so every helper it uses has to live inside it (see e2e/serialization.pw.test.ts).
 */
export function toggleDomTextSpacing(): TextSpacingReport {
  const ID = '__wcag1412__';
  const existing = document.getElementById(ID);
  if (existing) {
    existing.remove();
    return {
      applied: false, clippedCandidates: [], clippedTotal: 0, preexistingClips: 0,
      note: 'Injected style removed.'
    };
  }

  const clipStateOf = (el: Element): { y: boolean; x: boolean } => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return { y: false, x: false };
    const hidesY = cs.overflowY === 'hidden' || cs.overflowY === 'clip';
    const hidesX = cs.overflowX === 'hidden' || cs.overflowX === 'clip';
    return {
      y: hidesY && el.scrollHeight > el.clientHeight + 1,
      x: hidesX && el.scrollWidth > el.clientWidth + 1
    };
  };

  // Baseline first, with the page exactly as the visitor sees it.
  const all: Element[] = [];
  const candidates = document.querySelectorAll('body *');
  for (let i = 0; i < candidates.length; i++) {
    const el = candidates.item(i);
    if (el && !el.closest('svg, canvas')) all.push(el);
  }
  const before = all.map(clipStateOf);

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
  let clippedTotal = 0;
  let preexistingClips = 0;
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    const was = before[i];
    if (!el || !was) continue;
    const now = clipStateOf(el);
    if ((now.y && was.y) || (now.x && was.x)) preexistingClips++;
    const newlyY = now.y && !was.y;
    const newlyX = now.x && !was.x;
    if (!newlyY && !newlyX) continue;
    clippedTotal++;
    if (clipped.length < 25) {
      clipped.push({
        tag: el.tagName.toLowerCase(), cls: clsOf(el),
        text: (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40),
        clippedVertically: newlyY, clippedHorizontally: newlyX
      });
    }
  }
  return {
    applied: true, clippedCandidates: clipped, clippedTotal, preexistingClips,
    note: 'Only elements clipped BY the spacing override are listed; ' +
          String(preexistingClips) + ' element(s) were already clipped beforehand ' +
          '(visually-hidden text is clipped by design) and are excluded. ' +
          'Screenshot and compare; bounding-box checks do not detect overlap. ' +
          'SVG excluded — run toggleSvgTextSpacing for Recharts labels. Re-run to remove.'
  };
}

export interface SvgSpacingIssue {
  text: string; widthBefore: number | null; widthAfter: number | null;
  escapesLeft: boolean; escapesRight: boolean;
}
export interface SvgSpacingReport {
  applied: boolean; svgTextCount: number; escaping: SvgSpacingIssue[];
  /** Labels already outside their SVG before the override — a layout issue, not 1.4.12. */
  preexistingEscapes: number;
  note: string;
}

/**
 * SVG text is real text and is in scope for 1.4.12; canvas text is images-of-text.
 *
 * Measured before AND after, for the same reason as toggleDomTextSpacing: the criterion
 * is whether SETTING the spacing pushes a label out of its SVG. A chart axis whose last
 * tick already sits outside the plot at a narrow width fails this check on every run
 * regardless of spacing, which says nothing about 1.4.12 and hides the labels that the
 * spacing genuinely breaks. Those are still counted, in `preexistingEscapes`.
 */
export function toggleSvgTextSpacing(): SvgSpacingReport {
  const ID = '__wcag1412svg__';
  const existing = document.getElementById(ID);
  if (existing) {
    existing.remove();
    return {
      applied: false, svgTextCount: 0, escaping: [], preexistingEscapes: 0,
      note: 'SVG spacing style removed.'
    };
  }
  const widthOf = (t: SVGGraphicsElement): number | null => {
    try { return t.getBBox().width; } catch { return null; }
  };
  const escapeOf = (t: SVGGraphicsElement): { left: boolean; right: boolean } | null => {
    const svg = t.ownerSVGElement;
    if (!svg) return null;
    const sb = svg.getBoundingClientRect();
    const r = t.getBoundingClientRect();
    return { left: r.left < sb.left - 1, right: r.right > sb.right + 1 };
  };
  const nodes = Array.from(document.querySelectorAll('svg text')) as SVGGraphicsElement[];
  const before = nodes.map(t => ({ t, w: widthOf(t), escape: escapeOf(t) }));

  const style = document.createElement('style');
  style.id = ID;
  // line-height does not apply to SVG <text>; letter and word spacing do.
  style.textContent = 'svg text { letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }';
  document.head.appendChild(style);
  void document.documentElement.offsetHeight;

  const escaping: SvgSpacingIssue[] = [];
  let preexistingEscapes = 0;
  for (const { t, w, escape: was } of before) {
    const now = escapeOf(t);
    if (!now || !was) continue;
    if ((now.left && was.left) || (now.right && was.right)) preexistingEscapes++;
    const escapesLeft = now.left && !was.left;
    const escapesRight = now.right && !was.right;
    if (escapesLeft || escapesRight) {
      escaping.push({
        text: (t.textContent ?? '').trim().slice(0, 30),
        widthBefore: w, widthAfter: widthOf(t), escapesLeft, escapesRight
      });
    }
  }
  return {
    applied: true, svgTextCount: before.length, escaping: escaping.slice(0, 25),
    preexistingEscapes,
    note: 'Only labels pushed out BY the spacing are listed; ' + String(preexistingEscapes) +
          ' label(s) were already outside their SVG beforehand and are excluded. ' +
          'Bounds checks miss label collision — compare screenshots. Re-run to remove.'
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
