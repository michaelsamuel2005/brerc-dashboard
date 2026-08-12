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
    use: { ...devices['Desktop Firefox'], viewport: { width: 320, height: 640 } }
  }
];

export const A11Y_PROJECT_NAMES = a11yProjects.map(project => project.name);
