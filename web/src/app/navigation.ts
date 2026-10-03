// The site's primary navigation, in one place so the header, the drawer and the tests
// cannot disagree about what pages exist.

export interface NavItem {
  readonly href: string;
  readonly label: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", label: "Overview" },
  { href: "/explore", label: "Explore" },
  { href: "/species", label: "Species" },
  { href: "/records", label: "Records" },
  { href: "/about", label: "About the data" },
] as const;

// Reached from the footer rather than the primary nav: required reading, but not what
// a visitor came for. Both are obligations of a public sector body, not extras.
export const FOOTER_ITEMS: readonly NavItem[] = [
  { href: "/accessibility", label: "Accessibility statement" },
  { href: "/privacy", label: "Privacy" },
  { href: "/settings", label: "Settings" },
] as const;

/**
 * Which nav item should be marked `aria-current="page"`.
 *
 * A species page belongs under Species, and the overview only matches exactly — without
 * that, "/" would prefix-match every route and mark itself current everywhere.
 */
export function currentNavHref(pathname: string): string | null {
  if (pathname === "/") return "/";
  const match = NAV_ITEMS.filter((item) => item.href !== "/").find(
    (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
  );
  return match?.href ?? null;
}
