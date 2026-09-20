import { useEffect, useState } from "react";

/**
 * Hold a value still until it stops changing.
 *
 * Used by the species picker so typing does not fire one request per keystroke. At
 * 15,000–16,000 species (BRERC, client meeting 2) the search has to go to the server —
 * the catalogue cannot be held in the browser — so the delay is what keeps that from
 * becoming a request per letter.
 *
 * The timer is cleared on unmount and on every change, so a value that never settles
 * never fires, and nothing updates state after the component has gone.
 */
export function useDebouncedValue<T>(value: T, delayMs = 250): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    // A zero or negative delay means "no debounce" — apply immediately rather than
    // scheduling a timer that fires on the next tick, which tests would have to await.
    if (!(delayMs > 0)) {
      setSettled(value);
      return;
    }
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return settled;
}
