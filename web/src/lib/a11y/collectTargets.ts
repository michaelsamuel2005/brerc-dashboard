import type { TargetNode, GeometryConfidence } from './targetSpacing';

/**
 * Browser-side collector for SC 2.5.8.
 *
 * SELF-CONTAINED BY CONTRACT: references nothing from module scope. Playwright
 * serialises the function source and runs it in the page, where module bindings do not
 * exist — a helper closing over a module constant throws "ReferenceError: AA_MIN is not
 * defined" (verified against real Chromium). Keep every constant inline.
 *
 * Returns plain data only. All judgement happens in Node via classifyTargets().
 *
 *   const targets = await page.evaluate(collectTargets);
 *   const report  = classifyTargets(targets, { obstacles });
 */
export function collectTargets(): TargetNode[] {
  const SELECTOR = [
    'a[href]', 'button', 'input:not([type="hidden"])', 'select', 'textarea', 'summary',
    '[tabindex]:not([tabindex="-1"])', '[role="button"]', '[role="link"]', '[role="checkbox"]',
    '[role="tab"]', '[role="menuitem"]', '[role="switch"]', '[role="radio"]', '[role="option"]',
    '[onclick]',
    // Recharts attaches pointer handlers via React props, so bars carry no onclick
    // attribute and no role. Mark each <Cell>, not the parent <Bar>.
    '[data-a11y-pointer-target]'
  ].join(',');

  const out: TargetNode[] = [];
  let index = 0;

  const nodes = document.querySelectorAll(SELECTOR);
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes.item(i);
    if (!el) continue;
    // A closed <details> keeps descendant boxes queryable in some engines even though
    // they are not painted or operable. Only its <summary> is a visible target.
    const closedDetails = el.closest('details:not([open])');
    if (closedDetails !== null && el.closest('summary') === null) continue;
    // Focusable overflow regions support keyboard scrolling but are not activation
    // targets for pointer input. Native scrollbars remain user-agent controls.
    if (el.hasAttribute('data-a11y-non-pointer-target')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.pointerEvents === 'none') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;

    // --- Is the bounding box a fair measure of this target? ---
    // Parse numerically: user agents report an unset radius variously as "", "0",
    // "0px" or "0%", and a string comparison against "0px" alone flags every plain
    // control as rounded.
    // The shorthand is read too: not every engine expands `border-radius` into the
    // four longhands on the computed style.
    const radii = [cs.borderRadius, cs.borderTopLeftRadius, cs.borderTopRightRadius,
                   cs.borderBottomLeftRadius, cs.borderBottomRightRadius];
    let rounded = false;
    for (const v of radii) {
      const n = Number.parseFloat(v);
      if (Number.isFinite(n) && n > 0) { rounded = true; break; }
    }

    const clipped = cs.clipPath !== 'none' && cs.clipPath !== '';

    let transformed = false;
    if (cs.transform !== '' && cs.transform !== 'none') {
      const m = /matrix\(([^)]+)\)/.exec(cs.transform);
      const captured = m ? m[1] : undefined;
      if (captured !== undefined) {
        const parts = captured.split(',');
        const a = Number(parts[0] ?? NaN);
        const b = Number(parts[1] ?? NaN);
        const c = Number(parts[2] ?? NaN);
        const d = Number(parts[3] ?? NaN);
        // b != 0 catches rotation and skewY; c != 0 catches skewX; negative a/d catch flips.
        transformed = !Number.isFinite(a) || !Number.isFinite(d) ||
                      Math.abs(b) > 1e-3 || Math.abs(c) > 1e-3 || a < 0 || d < 0;
      } else {
        transformed = true;   // matrix3d or unparsed: assume not a plain rectangle
      }
    }

    // An SVG shape other than <rect> is not a rectangle.
    const svgNonRect = el.namespaceURI === 'http://www.w3.org/2000/svg' &&
                       el.tagName.toLowerCase() !== 'rect';

    // Ancestor clipping can reduce the visible hit area below the reported box.
    let ancestorClipped = false;
    let parent: Element | null = el.parentElement;
    while (parent !== null) {
      const ps = getComputedStyle(parent);
      const hides = (ps.clipPath !== 'none' && ps.clipPath !== '') ||
                    ps.overflow === 'hidden' || ps.overflow === 'clip' ||
                    ps.overflowX === 'hidden' || ps.overflowY === 'hidden';
      if (hides) {
        const pr = parent.getBoundingClientRect();
        if (r.left < pr.left - 0.5 || r.right > pr.right + 0.5 ||
            r.top < pr.top - 0.5 || r.bottom > pr.bottom + 0.5) {
          ancestorClipped = true;
          break;
        }
      }
      parent = parent.parentElement;
    }

    const confidence: GeometryConfidence =
      (rounded || clipped || transformed || svgNonRect || ancestorClipped)
        ? 'unverified' : 'verified-rectangular';

    const rawLabel = el.getAttribute('aria-label') ?? el.textContent ?? el.getAttribute('title') ?? '';
    const label = rawLabel.trim().replace(/\s+/g, ' ').slice(0, 60);

    out.push({
      index,
      label: label === '' ? `${el.tagName.toLowerCase()}#${index}` : label,
      // hasAttribute on the element ITSELF, never closest(): tagging a wrapper must not
      // exempt the controls inside it.
      exceptionClaim: el.hasAttribute('data-a11y-target-exception')
        ? el.getAttribute('data-a11y-target-exception')
        : null,
      sameActionGroup: el.getAttribute('data-a11y-same-action'),
      geometryConfidence: confidence,
      rect: {
        left: r.left, top: r.top, right: r.right, bottom: r.bottom,
        width: r.width, height: r.height
      }
    });
    index++;
  }

  return out;
}
