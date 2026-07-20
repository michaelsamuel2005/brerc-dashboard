// Accessible, plain-language loading / error / empty states. "No records here" is
// meaningful information, not an error.
export function LoadingState({ label = "content" }: { label?: string }) {
  return (
    <p role="status" aria-live="polite">
      Loading {label}…
    </p>
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div role="alert">
      <p>Sorry — {message ?? "something went wrong loading this section."}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ message = "No records here." }: { message?: string }) {
  return <p>{message}</p>;
}
