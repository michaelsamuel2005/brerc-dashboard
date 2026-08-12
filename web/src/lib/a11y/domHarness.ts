/**
 * jsdom does no layout, so getBoundingClientRect() returns zeros and every target would
 * be filtered out. This harness lets a test declare each element's box with
 * data-rect="left,top,width,height" and have the DOM report it.
 *
 * Test-only. Not shipped to the browser.
 */
export function installRectHarness(): () => void {
  const original = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function (this: Element): DOMRect {
    const spec = this.getAttribute('data-rect');
    if (spec === null) return original.call(this);
    const parts = spec.split(',').map(Number);
    const left = parts[0] ?? 0, top = parts[1] ?? 0;
    const width = parts[2] ?? 0, height = parts[3] ?? 0;
    return {
      left, top, width, height, right: left + width, bottom: top + height,
      x: left, y: top, toJSON: () => ({})
    } as DOMRect;
  };
  return () => { Element.prototype.getBoundingClientRect = original; };
}

/**
 * jsdom implements neither layout nor matchMedia. This gives documentElement a viewport
 * width and a matchMedia that answers "no" to every query, so diagnostics that read them
 * behave as they would in a real browser at a known width.
 */
export function installViewportHarness(width = 320, height = 640): () => void {
  const w = globalThis as unknown as { matchMedia: unknown; innerWidth: number; innerHeight: number };
  const priorMatchMedia = w.matchMedia;
  const priorInner = { width: w.innerWidth, height: w.innerHeight };

  const descriptors = ['clientWidth', 'clientHeight'] as const;
  const prior = descriptors.map(k =>
    ({ k, d: Object.getOwnPropertyDescriptor(Object.getPrototypeOf(document.documentElement), k) }));

  Object.defineProperty(document.documentElement, 'clientWidth', { value: width, configurable: true });
  Object.defineProperty(document.documentElement, 'clientHeight', { value: height, configurable: true });
  w.innerWidth = width;
  w.innerHeight = height;
  w.matchMedia = (query: string): { matches: boolean; media: string; addEventListener: () => void;
                                    removeEventListener: () => void; addListener: () => void;
                                    removeListener: () => void; onchange: null; dispatchEvent: () => boolean } => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => undefined, removeEventListener: () => undefined,
    addListener: () => undefined, removeListener: () => undefined,
    dispatchEvent: () => false
  });

  return () => {
    for (const { k, d } of prior) {
      Reflect.deleteProperty(document.documentElement, k);
      if (d) Object.defineProperty(Object.getPrototypeOf(document.documentElement), k, d);
    }
    w.matchMedia = priorMatchMedia;
    w.innerWidth = priorInner.width;
    w.innerHeight = priorInner.height;
  };
}
