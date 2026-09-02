import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  configureReleaseRecovery,
  enforceReleaseCoherence,
  getReleaseCoherenceSnapshot,
  ReleaseCoherenceError,
  resetReleaseCoherenceForTests,
  retryReleaseRecovery,
} from "./releaseCoherence";

const OLD = {
  releaseId: "00000000-0000-4000-8000-000000000001",
  datasetVersion: "dataset-v1",
};
const NEW = {
  releaseId: "00000000-0000-4000-8000-000000000002",
  datasetVersion: "dataset-v2",
};

describe("page-wide release coherence", () => {
  beforeEach(resetReleaseCoherenceForTests);
  afterEach(resetReleaseCoherenceForTests);

  it("rejects a mixed response, rejects stale in-flight responses, then accepts only the authoritative release", async () => {
    let finishRecovery: ((identity: typeof NEW) => void) | undefined;
    const recovery = vi.fn(
      () =>
        new Promise<typeof NEW>((resolve) => {
          finishRecovery = resolve;
        }),
    );
    configureReleaseRecovery(recovery);

    expect(enforceReleaseCoherence({ ...OLD, payload: "old" }).payload).toBe("old");
    expect(getReleaseCoherenceSnapshot()).toEqual({ phase: "stable", identity: OLD });

    expect(() => enforceReleaseCoherence({ ...NEW, payload: "new" })).toThrow(
      ReleaseCoherenceError,
    );
    expect(getReleaseCoherenceSnapshot().phase).toBe("recovering");

    // A request that began before the switch may arrive after the new response.
    // It cannot flip the baseline back or enter the cache while recovery runs.
    expect(() => enforceReleaseCoherence({ ...OLD, payload: "late-old" })).toThrow(
      /recovery is in progress/,
    );

    await vi.waitFor(() => expect(recovery).toHaveBeenCalledOnce());
    finishRecovery?.(NEW);
    await vi.waitFor(() =>
      expect(getReleaseCoherenceSnapshot()).toEqual({ phase: "stable", identity: NEW }),
    );

    expect(enforceReleaseCoherence({ ...NEW, payload: "current" }).payload).toBe("current");
  });

  it("treats a dataset-version change under the same release UUID as incoherent", () => {
    configureReleaseRecovery(async () => NEW);
    enforceReleaseCoherence(OLD);
    expect(() =>
      enforceReleaseCoherence({ ...OLD, datasetVersion: "mutated-version" }),
    ).toThrow(ReleaseCoherenceError);
    expect(getReleaseCoherenceSnapshot().phase).toBe("recovering");
  });

  it("allows the authoritative provenance request through only for recovery anchoring", () => {
    enforceReleaseCoherence(OLD);
    expect(
      enforceReleaseCoherence(NEW, { authority: true }),
    ).toEqual(NEW);
    expect(getReleaseCoherenceSnapshot()).toEqual({ phase: "stable", identity: OLD });
  });

  it("stays fail-closed after recovery failure and supports an explicit retry", async () => {
    let attempts = 0;
    configureReleaseRecovery(async () => {
      attempts += 1;
      if (attempts === 1) throw new Error("temporary provenance failure");
      return NEW;
    });

    enforceReleaseCoherence(OLD);
    expect(() => enforceReleaseCoherence(NEW)).toThrow(ReleaseCoherenceError);
    await vi.waitFor(() => expect(getReleaseCoherenceSnapshot().phase).toBe("failed"));
    expect(() => enforceReleaseCoherence(NEW)).toThrow(/recovery failed/);

    retryReleaseRecovery();
    expect(getReleaseCoherenceSnapshot().phase).toBe("recovering");
    await vi.waitFor(() =>
      expect(getReleaseCoherenceSnapshot()).toEqual({ phase: "stable", identity: NEW }),
    );
  });
});
