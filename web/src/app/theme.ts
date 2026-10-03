// Appearance preferences: colour theme and row density.
//
// Both are stored on the visitor's own device and never sent anywhere. There is no
// account, no cookie and no server round-trip, so this cannot identify anyone — worth
// stating plainly in the privacy notice rather than leaving a reader to wonder what
// "these persist on this device" means.
//
// "system" is the default and is expressed by REMOVING the attribute, so the
// `prefers-color-scheme` block in tokens.css governs. Writing data-theme="light" for a
// visitor who never chose would override their operating system, which is the one thing
// a theme control must not do silently.

export const THEMES = ["system", "light", "dark"] as const;
export const DENSITIES = ["comfortable", "compact"] as const;

export type Theme = (typeof THEMES)[number];
export type Density = (typeof DENSITIES)[number];

export const THEME_KEY = "brerc-theme";
export const DENSITY_KEY = "brerc-density";

/** Narrow an unknown stored string to a supported theme, defaulting to "system". */
export function readTheme(raw: string | null): Theme {
  return (THEMES as readonly string[]).includes(raw ?? "") ? (raw as Theme) : "system";
}

/** Narrow an unknown stored string to a supported density, defaulting to comfortable. */
export function readDensity(raw: string | null): Density {
  return (DENSITIES as readonly string[]).includes(raw ?? "")
    ? (raw as Density)
    : "comfortable";
}

/**
 * The value the `data-theme` attribute should take, or null to remove it.
 * Kept separate from the DOM so the rule can be tested without a document.
 */
export function themeAttribute(theme: Theme): string | null {
  return theme === "system" ? null : theme;
}

/** Likewise for density: comfortable is the default, so it carries no attribute. */
export function densityAttribute(density: Density): string | null {
  return density === "comfortable" ? null : density;
}

/**
 * Storage can throw — Safari in private browsing, or a browser configured to block it.
 * An appearance preference is never worth taking the page down for, so both accessors
 * degrade to the default rather than propagating.
 */
function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* preference simply will not persist; the session still honours it */
  }
}

export function storedTheme(): Theme {
  return readTheme(safeGet(THEME_KEY));
}

export function storedDensity(): Density {
  return readDensity(safeGet(DENSITY_KEY));
}

/** Reflect a theme onto the document root. Exported for the settings controls. */
export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  const value = themeAttribute(theme);
  if (value === null) root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", value);
}

export function applyDensity(
  density: Density,
  root: HTMLElement = document.documentElement,
): void {
  const value = densityAttribute(density);
  if (value === null) root.removeAttribute("data-density");
  else root.setAttribute("data-density", value);
}

export function setTheme(theme: Theme): void {
  safeSet(THEME_KEY, theme);
  applyTheme(theme);
}

export function setDensity(density: Density): void {
  safeSet(DENSITY_KEY, density);
  applyDensity(density);
}

/**
 * Apply stored preferences. Called from main.tsx before React renders, so the first
 * paint of the app is already in the right theme.
 */
export function applyStoredPreferences(): void {
  applyTheme(storedTheme());
  applyDensity(storedDensity());
}

/** What the theme button should switch to: the opposite of what is on screen now. */
export function nextTheme(current: Theme, systemPrefersDark: boolean): Theme {
  if (current === "system") return systemPrefersDark ? "light" : "dark";
  return current === "dark" ? "light" : "dark";
}
