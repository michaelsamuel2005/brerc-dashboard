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
    <p role="status" aria-live="polite">
      {announced}
    </p>
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry: () => void }) {
  return (
    <div role="alert">
      <p>Sorry — {message ?? "something went wrong loading this section."}</p>
      <button type="button" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

export function EmptyState({ message = "No records here." }: { message?: string }) {
  const [announced, setAnnounced] = useState("");
  useEffect(() => {
    setAnnounced(message);
  }, [message]);

  return (
    <p role="status" aria-live="polite">
      {announced}
    </p>
  );
}
