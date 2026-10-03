import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSyncExternalStore, type ReactNode } from "react";
import { getProvenance } from "../lib/api/endpoints";
import {
  configureReleaseRecovery,
  getReleaseCoherenceSnapshot,
  retryReleaseRecovery,
  subscribeReleaseCoherence,
} from "../lib/api/releaseCoherence";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

configureReleaseRecovery(async () => {
  // Stop stale in-flight responses, then remove every cached fragment of the
  // former page. The recovery request is deliberately outside TanStack Query:
  // it must complete before the application tree is allowed to remount.
  await queryClient.cancelQueries();
  queryClient.clear();
  const provenance = await getProvenance({ releaseAuthority: true });
  return {
    releaseId: provenance.releaseId,
    datasetVersion: provenance.datasetVersion,
  };
});

function ReleaseCoherenceBoundary({ children }: { children: ReactNode }) {
  const snapshot = useSyncExternalStore(
    subscribeReleaseCoherence,
    getReleaseCoherenceSnapshot,
    getReleaseCoherenceSnapshot,
  );

  if (snapshot.phase === "unbound" || snapshot.phase === "stable") return children;

  if (snapshot.phase === "recovering") {
    return (
      <main id="main" className="directory-page" aria-live="polite">
        <span className="eyebrow">Data update</span>
        <h1 className="page-title">Refreshing the published data</h1>
        <p className="page-lead">
          A new BRERC data release became active. The dashboard is reloading all data
          together so figures from different releases are never combined.
        </p>
      </main>
    );
  }

  return (
    <main id="main" className="directory-page" role="alert">
      <span className="eyebrow">Data unavailable</span>
      <h1 className="page-title">The published data could not be refreshed</h1>
      <p className="page-lead">
        The dashboard has hidden the previous page rather than combine different data
        releases. Check the connection and try again.
      </p>
      <button type="button" className="btn" onClick={retryReleaseRecovery}>
        Try again
      </button>
    </main>
  );
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ReleaseCoherenceBoundary>{children}</ReleaseCoherenceBoundary>
    </QueryClientProvider>
  );
}
