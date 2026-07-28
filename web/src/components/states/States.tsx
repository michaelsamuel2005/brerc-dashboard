// Accessible, plain-language loading / error / empty states. "No records here" is
// meaningful information, not an error.
export function LoadingState({ label = "content" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" aria-label={`Loading ${label}`}>
      <p>Loading {label}…</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div role="alert">
      <h3>Sorry, something went wrong</h3>
      <p>{message ?? "something went wrong loading this section."}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title = "No records here", message = "There is nothing to show right now." }: { title?: string; message?: string }) {
  return (
    <div role="status" aria-live="polite">
      <h3>{title}</h3>
      <p>{message}</p>
    </div>
  );
}
