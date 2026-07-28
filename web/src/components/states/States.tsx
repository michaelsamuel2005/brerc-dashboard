// Accessible, plain-language loading / error / empty states. "No records here" is
// meaningful information, not an error.
export function LoadingState({ label = "content" }: { label?: string }) {
  return (
<<<<<<< HEAD
    <div role="status" aria-live="polite" aria-label={`Loading ${label}`}>
      <p>Loading {label}…</p>
    </div>
=======
    <p role="status" aria-live="polite">
      Loading {label}…
    </p>
>>>>>>> bcc692d7f270662e68659a562f2e54bb600edeb3
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div role="alert">
<<<<<<< HEAD
      <h3>Sorry, something went wrong</h3>
      <p>{message ?? "something went wrong loading this section."}</p>
=======
      <p>Sorry — {message ?? "something went wrong loading this section."}</p>
>>>>>>> bcc692d7f270662e68659a562f2e54bb600edeb3
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

<<<<<<< HEAD
export function EmptyState({ title = "No records here", message = "There is nothing to show right now." }: { title?: string; message?: string }) {
  return (
    <div role="status" aria-live="polite">
      <h3>{title}</h3>
      <p>{message}</p>
    </div>
  );
=======
export function EmptyState({ message = "No records here." }: { message?: string }) {
  return <p>{message}</p>;
>>>>>>> bcc692d7f270662e68659a562f2e54bb600edeb3
}
