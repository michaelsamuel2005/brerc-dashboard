import { useEffect, useRef } from "react";
import { Link } from "wouter";
import type { NavItem } from "./navigation";

interface Props {
  items: readonly NavItem[];
  pathname: string;
  onClose: () => void;
}

const FOCUSABLE = 'a[href], button:not([disabled])';

/**
 * The small-screen navigation, as a real modal dialog.
 *
 * Implemented by hand rather than with <dialog showModal()> because that API is still
 * missing from the jsdom version the unit tests run in, and a control whose keyboard
 * behaviour is untestable is not one to ship on a page that must meet WCAG 2.2 AA.
 *
 * What it has to get right, and what the tests below cover:
 *  - focus moves into the dialog on open (2.4.3 Focus Order)
 *  - Escape closes it (2.1.2 No Keyboard Trap)
 *  - Tab cycles inside it and cannot reach the page behind (4.1.2, 2.4.3)
 *  - focus returns to the button that opened it (2.4.3)
 */
export function NavDrawer({ items, pathname, onClose }: Props) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  // Captured on mount: the element that had focus is the trigger, and focus must go
  // back there on close or a keyboard user is dropped at the top of the document.
  const openerRef = useRef<Element | null>(null);

  useEffect(() => {
    openerRef.current = document.activeElement;
    const sheet = sheetRef.current;
    sheet?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    return () => {
      const opener = openerRef.current;
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const sheet = sheetRef.current;
      if (!sheet) return;
      const focusable = [...sheet.querySelectorAll<HTMLElement>(FOCUSABLE)];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      // Wrap at both ends, so Tab never lands on the page behind the overlay.
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="drawer">
      {/* The dimmed area is a pointer-only convenience. It is deliberately NOT keyboard
          operable and is hidden from assistive technology, because two keyboard routes
          out already exist and are tested: Escape, and the explicit "Close menu" button
          at the end of the dialog. Making the backdrop focusable would add a second,
          unlabelled way to leave the menu and put an empty element in the tab order. */}
      <div className="drawer-backdrop" aria-hidden="true" onClick={onClose} />
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        ref={sheetRef}
      >
        <h2>Menu</h2>
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={pathname === item.href ? "page" : undefined}
            onClick={onClose}
          >
            {item.label}
          </Link>
        ))}
        <button type="button" className="btn-ghost" onClick={onClose}>
          Close menu
        </button>
      </div>
    </div>
  );
}
