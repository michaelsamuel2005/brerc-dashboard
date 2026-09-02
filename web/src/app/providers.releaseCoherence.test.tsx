import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useSpeciesList, useSummary } from "../lib/api/queries";
import { summaryFixture, speciesListFixture, provenanceFixture } from "../test/fixtures";
import { server } from "../test/msw/server";
import { Providers } from "./providers";

const NEW_IDENTITY = {
  releaseId: "00000000-0000-4000-8000-000000000002",
  datasetVersion: "fixture-contract-v2",
} as const;

function TestPage() {
  const summary = useSummary();
  const species = useSpeciesList();
  if (!summary.data || !species.data) return <p>Loading test page</p>;
  return (
    <main data-testid="assembled-page">
      <p>Summary release: {summary.data.releaseId}</p>
      <p>Species release: {species.data.releaseId}</p>
      <button type="button" onClick={() => void summary.refetch()}>
        Check for a release
      </button>
    </main>
  );
}

it("hides an assembled page, anchors the new release, and refetches every fragment together", async () => {
  let current: "old" | "new" = "old";
  let allowRecovery: (() => void) | undefined;
  const recoveryGate = new Promise<void>((resolve) => {
    allowRecovery = resolve;
  });
  const identity = () =>
    current === "old"
      ? {
          releaseId: provenanceFixture.releaseId,
          datasetVersion: provenanceFixture.datasetVersion,
        }
      : NEW_IDENTITY;

  server.use(
    http.get("*/api/summary", () =>
      HttpResponse.json({ ...summaryFixture, ...identity() }),
    ),
    http.get("*/api/species", () =>
      HttpResponse.json({ ...speciesListFixture, ...identity() }),
    ),
    http.get("*/api/meta/provenance", async () => {
      if (current === "new") await recoveryGate;
      return HttpResponse.json({ ...provenanceFixture, ...identity() });
    }),
  );

  const user = userEvent.setup();
  render(
    <Providers>
      <TestPage />
    </Providers>,
  );

  expect(await screen.findByText(`Summary release: ${provenanceFixture.releaseId}`)).not.toBeNull();
  expect(screen.getByText(`Species release: ${provenanceFixture.releaseId}`)).not.toBeNull();

  current = "new";
  await user.click(screen.getByRole("button", { name: "Check for a release" }));

  expect(
    await screen.findByRole("heading", { name: "Refreshing the published data" }),
  ).not.toBeNull();
  expect(screen.queryByTestId("assembled-page")).toBeNull();

  await act(async () => allowRecovery?.());

  expect(await screen.findByText(`Summary release: ${NEW_IDENTITY.releaseId}`)).not.toBeNull();
  expect(screen.getByText(`Species release: ${NEW_IDENTITY.releaseId}`)).not.toBeNull();
});
