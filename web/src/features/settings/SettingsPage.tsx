import { useState } from "react";
import { Link } from "wouter";
import {
  type Density,
  DENSITIES,
  type Theme,
  THEMES,
  setDensity,
  setTheme,
  storedDensity,
  storedTheme,
} from "../../app/theme";

const THEME_LABELS: Record<Theme, string> = {
  system: "Match my device",
  light: "Light",
  dark: "Dark",
};

const DENSITY_LABELS: Record<Density, string> = {
  comfortable: "Comfortable",
  compact: "Compact",
};

/**
 * Appearance preferences.
 *
 * Implemented as `aria-pressed` toggle buttons rather than a radio group because each
 * one takes effect the moment it is pressed — there is no Save, so a radio group would
 * imply a form that does not exist. The pressed state is what a screen reader announces,
 * and it is the same state the visitor can see.
 */
export function SettingsPage() {
  const [theme, setLocalTheme] = useState<Theme>(() => storedTheme());
  const [density, setLocalDensity] = useState<Density>(() => storedDensity());

  function chooseTheme(next: Theme) {
    setTheme(next);
    setLocalTheme(next);
  }

  function chooseDensity(next: Density) {
    setDensity(next);
    setLocalDensity(next);
  }

  return (
    <main id="main">
      <span className="eyebrow">Preferences</span>
      <h1 className="page-title" tabIndex={-1}>Settings</h1>
      <p className="page-lead">
        These change how the site looks on this device only. They are stored in your
        browser, are never sent anywhere, and cannot identify you — see the{" "}
        <Link href="/privacy">privacy notice</Link>.
      </p>

      <section className="settings-group" aria-labelledby="theme-heading">
        <h2 id="theme-heading">Colour theme</h2>
        <p>
          &ldquo;Match my device&rdquo; follows your operating system&rsquo;s light or dark
          setting, and is the default. Both themes are checked against the same contrast
          requirements.
        </p>
        <div className="choices" role="group" aria-labelledby="theme-heading">
          {THEMES.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={theme === option}
              onClick={() => chooseTheme(option)}
            >
              {THEME_LABELS[option]}
            </button>
          ))}
        </div>
      </section>

      <section className="settings-group" aria-labelledby="density-heading">
        <h2 id="density-heading">Row spacing</h2>
        <p>
          Compact fits more rows on screen in the data tables. Buttons and links stay at
          their full size either way, so nothing becomes harder to tap.
        </p>
        <div className="choices" role="group" aria-labelledby="density-heading">
          {DENSITIES.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={density === option}
              onClick={() => chooseDensity(option)}
            >
              {DENSITY_LABELS[option]}
            </button>
          ))}
        </div>
      </section>

      <section className="settings-group" aria-labelledby="motion-heading">
        <h2 id="motion-heading">Motion</h2>
        <p>
          There is no setting here on purpose. The site already honours your system&rsquo;s
          &ldquo;reduce motion&rdquo; preference: map panning becomes instant and animations
          are switched off, without you having to find this page.
        </p>
      </section>
    </main>
  );
}
