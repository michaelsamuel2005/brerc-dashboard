/**
 * Page-wide atomic-release coherence.
 *
 * PostgreSQL REPEATABLE READ makes one API response internally consistent, but
 * a React page is assembled from several responses.  This controller pins the
 * first release identity the page observes.  A response from another release
 * is rejected before TanStack Query can cache it, all page content is hidden,
 * and one fresh provenance request establishes the currently active release.
 * Only after the query cache has been cleared and that recovery succeeds may
 * the page mount and fetch again.
 */

export interface ReleaseIdentity {
  releaseId: string;
  datasetVersion: string;
}

export type ReleaseCoherenceSnapshot =
  | { phase: "unbound" }
  | { phase: "stable"; identity: ReleaseIdentity }
  | {
      phase: "recovering";
      previous: ReleaseIdentity;
      observed: ReleaseIdentity;
    }
  | { phase: "failed"; error: Error };

export class ReleaseCoherenceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReleaseCoherenceError";
  }
}

type RecoveryHandler = () => Promise<ReleaseIdentity>;
type Listener = () => void;

let snapshot: ReleaseCoherenceSnapshot = { phase: "unbound" };
let recoveryHandler: RecoveryHandler | null = null;
let recoveryGeneration = 0;
const listeners = new Set<Listener>();

function sameIdentity(left: ReleaseIdentity, right: ReleaseIdentity): boolean {
  return left.releaseId === right.releaseId && left.datasetVersion === right.datasetVersion;
}

function publish(next: ReleaseCoherenceSnapshot): void {
  snapshot = next;
  for (const listener of listeners) listener();
}

function identityFrom(value: unknown): ReleaseIdentity | null {
  if (typeof value !== "object" || value === null) return null;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.releaseId === "string" && typeof candidate.datasetVersion === "string"
    ? { releaseId: candidate.releaseId, datasetVersion: candidate.datasetVersion }
    : null;
}

async function runRecovery(generation: number): Promise<void> {
  const handler = recoveryHandler;
  if (handler === null) {
    if (generation === recoveryGeneration) {
      publish({
        phase: "failed",
        error: new ReleaseCoherenceError("No release recovery handler is configured"),
      });
    }
    return;
  }

  try {
    const identity = await handler();
    if (!identity.releaseId || !identity.datasetVersion) {
      throw new ReleaseCoherenceError("Release recovery returned an invalid identity");
    }
    if (generation === recoveryGeneration) publish({ phase: "stable", identity });
  } catch (error) {
    if (generation !== recoveryGeneration) return;
    publish({
      phase: "failed",
      error: error instanceof Error ? error : new Error("Release recovery failed"),
    });
  }
}

function beginRecovery(previous: ReleaseIdentity, observed: ReleaseIdentity): void {
  if (snapshot.phase === "recovering") return;
  publish({ phase: "recovering", previous, observed });
  const generation = ++recoveryGeneration;
  // Do not clear/cancel the query cache from inside a queryFn's synchronous
  // resolution path.  The microtask runs immediately after the mismatching
  // response has been rejected and cannot enter the cache.
  queueMicrotask(() => void runRecovery(generation));
}

/** Configure the one recovery path owned by the application QueryClient. */
export function configureReleaseRecovery(handler: RecoveryHandler): void {
  recoveryHandler = handler;
}

/**
 * Validate a parsed API response before returning it to TanStack Query.
 * Health is database-independent and has no identity, so it passes through.
 */
export function enforceReleaseCoherence<T>(
  value: T,
  options: { authority?: boolean } = {},
): T {
  const observed = identityFrom(value);
  if (observed === null || options.authority === true) return value;

  if (snapshot.phase === "unbound") {
    publish({ phase: "stable", identity: observed });
    return value;
  }
  if (snapshot.phase === "stable") {
    if (sameIdentity(snapshot.identity, observed)) return value;
    const previous = snapshot.identity;
    beginRecovery(previous, observed);
    throw new ReleaseCoherenceError(
      `Publication release changed from ${previous.releaseId} to ${observed.releaseId}`,
    );
  }

  throw new ReleaseCoherenceError(
    snapshot.phase === "recovering"
      ? "Publication release recovery is in progress"
      : "Publication release recovery failed",
  );
}

export function getReleaseCoherenceSnapshot(): ReleaseCoherenceSnapshot {
  return snapshot;
}

export function subscribeReleaseCoherence(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Re-run the authoritative recovery after an operator/network failure. */
export function retryReleaseRecovery(): void {
  if (snapshot.phase !== "failed") return;
  publish({ phase: "recovering", previous: { releaseId: "unknown", datasetVersion: "unknown" }, observed: { releaseId: "unknown", datasetVersion: "unknown" } });
  const generation = ++recoveryGeneration;
  queueMicrotask(() => void runRecovery(generation));
}

/** Test isolation only; production code must never unpin a release directly. */
export function resetReleaseCoherenceForTests(): void {
  recoveryGeneration += 1;
  recoveryHandler = null;
  publish({ phase: "unbound" });
}
