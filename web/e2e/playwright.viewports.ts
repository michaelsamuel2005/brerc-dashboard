import { devices } from '@playwright/test';

/**
 * The five constrained/mobile viewports plus desktop and wide-screen verification.
 *
 * V1 320x640 is the normative SC 1.4.10 Reflow width — W3C: "320 CSS pixels is
 * equivalent to a starting viewport width of 1280 CSS pixels wide at 400% zoom".
 * The rest are real-device widths and the short-landscape case that triggers SC 2.4.11.
 *
 * Viewport dimensions alone do not emulate iOS Safari, so WebKit and Firefox projects
 * are included rather than relying on a resized Chromium.
 */

export const A11Y_VIEWPORTS = [
  { id: 'V1', width: 320, height: 640, why: 'normative Reflow width (SC 1.4.10)' },
  { id: 'V2', width: 360, height: 640, why: 'worst-case Android' },
  { id: 'V3', width: 390, height: 844, why: 'most common iOS logical width' },
  { id: 'V4', width: 768, height: 1024, why: 'tablet portrait breakpoint' },
  { id: 'V5', width: 844, height: 390, why: 'landscape, short viewport (SC 1.3.4, 2.4.11)' },
  { id: 'V6', width: 1440, height: 900, why: 'desktop layout and pointer controls' },
  { id: 'V7', width: 1920, height: 1080, why: 'wide-screen layout and line-length guard' }
] as const;

export const a11yProjects = [
  ...A11Y_VIEWPORTS.map(v => ({
    name: `a11y-chromium-${v.id}-${v.width}x${v.height}`,
    testMatch: /a11y-mobile\.spec\.ts/,
    use: { ...devices['Desktop Chrome'], viewport: { width: v.width, height: v.height },
           hasTouch: true, isMobile: true, deviceScaleFactor: 2 }
  })),
  {
    name: 'a11y-webkit-V3-390x844',
    testMatch: /a11y-mobile\.spec\.ts/,
    use: { ...devices['Desktop Safari'], viewport: { width: 390, height: 844 },
           hasTouch: true, deviceScaleFactor: 3 }
  },
  {
    name: 'a11y-firefox-V1-320x640',
    testMatch: /a11y-mobile\.spec\.ts/,
    use: {
      ...devices['Desktop Firefox'],
      viewport: { width: 320, height: 640 },
      // HEADED on CI, headless everywhere else — the opposite of the usual rule, for a
      // reason worth recording. The runner has no GPU and no display, and headless
      // Firefox on Linux never creates a WebGL context there: MapLibre errors at
      // construction, the app correctly renders its no-map fallback, and every
      // map-applicable state fails with the canvas absent from the DOM.
      // webgl.force-enabled alone was tried (c553de3's run) and changed nothing — the
      // blocklist override presupposes a GL context to grant, and headless Firefox has
      // no display to create one against. A HEADED Firefox under Xvfb gets a real X
      // display and Mesa's software GL — the standard way to give Firefox WebGL on a
      // GPU-less runner; ci.yml wraps the e2e step in xvfb-run for this. On macOS,
      // headless Firefox renders the map fine (full local pass), so headed mode is
      // scoped to CI and local runs are unchanged.
      headless: process.env['CI'] !== 'true',
      launchOptions: {
        firefoxUserPrefs: {
          // Mesa's llvmpipe is software rendering, which Firefox's blocklist refuses
          // for WebGL by default; force it past the blocklist. Launch-time only: it
          // changes how Firefox starts, never what the tests accept.
          'webgl.force-enabled': true
        }
      }
    }
  }
];

export const A11Y_PROJECT_NAMES = a11yProjects.map(project => project.name);
