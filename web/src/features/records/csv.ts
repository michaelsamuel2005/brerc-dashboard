// CSV of the grid-square table the visitor is looking at.
//
// Scope, deliberately: the rows currently on screen for ONE species, at the published
// capture resolution — the same numbers already rendered as text. It adds no information
// and so creates no new disclosure. What it is NOT is a bulk export of the whole
// dataset: aggregating across every species is a different risk (and a data-licensing
// question BRERC has not answered), so there is no "download everything" button and
// this module cannot be used to build one.
//
// The attribution line is part of the file, not a footnote on the page, because a CSV
// travels away from the site that explained it.

export interface CellRow {
  readonly cellId: string;
  readonly precisionMetres: number;
  readonly recordCount: number;
  readonly verifiedCount: number | null;
}

/**
 * Quote a field for CSV.
 *
 * Also neutralises spreadsheet formula injection: a value starting =, +, - or @ is
 * executed by Excel and Sheets when the file is opened. None of our values should ever
 * start that way — but "should never" is not a control, and a grid reference is
 * ultimately a string from the database.
 */
export function csvField(value: string | number | null): string {
  if (value === null) return "";
  const text = String(value);
  const risky = /^[=+\-@\t\r]/.test(text);
  const escaped = text.replace(/"/g, '""');
  return risky ? `"'${escaped}"` : `"${escaped}"`;
}

export function toCsv(
  rows: readonly CellRow[],
  options: { speciesName: string; verificationAvailable: boolean; retrieved: string },
): string {
  const header = ["Grid square", "Capture resolution (m)", "Records"];
  if (options.verificationAvailable) header.push("Verified");

  const lines = [
    // Comment rows first: every spreadsheet reads them as data, which is the point —
    // the licence should be impossible to open the file without seeing.
    `# ${options.speciesName} — grid-square summary`,
    "# Source: Bristol Regional Environmental Records Centre (BRERC)",
    "# Locations are generalised to the stated capture resolution. Not exact locations.",
    "# Counts reflect recording effort, not abundance or true distribution.",
    `# Retrieved: ${options.retrieved}`,
    header.map(csvField).join(","),
  ];

  for (const row of rows) {
    const fields: (string | number | null)[] = [
      row.cellId,
      row.precisionMetres,
      row.recordCount,
    ];
    if (options.verificationAvailable) fields.push(row.verifiedCount);
    lines.push(fields.map(csvField).join(","));
  }

  // CRLF: the line ending RFC 4180 specifies and Excel expects.
  return `${lines.join("\r\n")}\r\n`;
}

/** A filename that says what the file is without leaking anything. */
export function csvFilename(speciesName: string): string {
  const slug = speciesName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `brerc-${slug || "species"}-grid-squares.csv`;
}
