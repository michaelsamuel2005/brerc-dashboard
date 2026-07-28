// Accessible, plain-language loading / error / empty states. "No records here" is
// meaningful information, not an error.
import { useEffect, useState } from "react";

export function LoadingState({ label = "content" }: { label?: string }) {
  // A live region announces only when its text CHANGES after mount, not when
  // it already has content on first render — so we start empty and fill it in.
  const [announced, setAnnounced] = useState("");
  useEffect(() => {
    setAnnounced(`Loading ${label}…`);
  }, [label]);

  return (
    <div role="status" aria-live="polite" aria-label={`Loading ${label}`}>
      <p>{announced}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry: () => void }) {
  return (
    <div role="alert">
      <h3>Sorry, something went wrong</h3>
      <p>{message ?? "something went wrong loading this section."}</p>
      <button type="button" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

export function EmptyState({ title = "No records here", message = "There is nothing to show right now." }: { title?: string; message?: string }) {
  const [announced, setAnnounced] = useState("");
  useEffect(() => {
    setAnnounced(message);
  }, [message]);

  return (
    <div role="status" aria-live="polite">
      <h3>{title}</h3>
      <p>{announced}</p>
    </div>
  );
}
