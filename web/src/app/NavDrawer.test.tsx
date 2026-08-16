import { fireEvent, render, screen } from "@testing-library/react";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { describe, expect, it, vi } from "vitest";
import { NavDrawer } from "./NavDrawer";
import { NAV_ITEMS } from "./navigation";

function renderDrawer(onClose = vi.fn(), pathname = "/species") {
  const { hook } = memoryLocation({ path: pathname });
  const trigger = document.createElement("button");
  trigger.textContent = "Open menu";
  document.body.append(trigger);
  trigger.focus();
  const utils = render(
    <Router hook={hook}>
      <NavDrawer items={NAV_ITEMS} pathname={pathname} onClose={onClose} />
    </Router>,
  );
  return { ...utils, onClose, trigger };
}

describe("NavDrawer", () => {
  it("is a modal dialog with an accessible name", () => {
    renderDrawer();
    const dialog = screen.getByRole("dialog", { name: "Menu" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("moves focus into the dialog on open", () => {
    renderDrawer();
    // Without this a keyboard user opens the menu and their focus stays behind it.
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Overview" }));
  });

  it("returns focus to the button that opened it", () => {
    const { unmount, trigger } = renderDrawer();
    unmount();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on Escape", () => {
    const { onClose } = renderDrawer();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes when the dimmed area is clicked, but not the sheet itself", () => {
    const { onClose } = renderDrawer();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(document.querySelector(".drawer-backdrop") as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("wraps Tab at the end and Shift+Tab at the start, so focus cannot escape behind it", () => {
    renderDrawer();
    const focusable = [...(document.querySelector(".sheet")?.querySelectorAll<HTMLElement>("a[href], button") ?? [])];
    const first = focusable[0] as HTMLElement;
    const last = focusable[focusable.length - 1] as HTMLElement;

    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(first);

    first.focus();
    fireEvent.keyDown(document, { key: "Shift", shiftKey: true });
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("marks the current page and only the current page", () => {
    renderDrawer(vi.fn(), "/species");
    const current = screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Species");
  });

  it("closes when a destination is chosen, so the overlay does not cover the new page", () => {
    const { onClose } = renderDrawer();
    fireEvent.click(screen.getByRole("link", { name: "About the data" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("offers an explicit close control for people who cannot press Escape", () => {
    const { onClose } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
