import { describe, expect, it } from "vitest";
import { csvField, csvFilename, toCsv } from "./csv";

const OPTIONS = { speciesName: "Adder", verificationAvailable: true, retrieved: "2026-08-16" };
const ROWS = [
  { cellId: "ST5872", precisionMetres: 1000, recordCount: 12, verifiedCount: 9 },
  { cellId: "ST5972", precisionMetres: 1000, recordCount: 3, verifiedCount: null },
];

describe("csvField", () => {
  it("quotes every field, so a comma in a value cannot split a row", () => {
    expect(csvField("plain")).toBe('"plain"');
    expect(csvField("a,b")).toBe('"a,b"');
    expect(csvField(12)).toBe('"12"');
  });

  it("doubles embedded quotes per RFC 4180", () => {
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
  });

  it("writes an empty field for null rather than the word null", () => {
    expect(csvField(null)).toBe("");
  });

  it("neutralises spreadsheet formula injection", () => {
    // Excel and Sheets execute a cell beginning =, +, - or @ on open. A leading
    // apostrophe makes the cell a literal string instead.
    // Read the field back the way a CSV parser would: strip the wrapping quotes and
    // undouble the inner ones. What remains must be the original text with a leading
    // apostrophe — the value is preserved, only its formula-ness is removed.
    const parse = (field: string) => field.slice(1, -1).replace(/""/g, '"');
    for (const payload of ["=1+1", '=HYPERLINK("http://evil.test")', "+1", "-1", "@SUM(A1)"]) {
      const field = csvField(payload);
      expect(field.startsWith("\"'")).toBe(true);
      expect(parse(field)).toBe(`'${payload}`);
    }
  });

  it("leaves an ordinary grid reference untouched apart from quoting", () => {
    expect(csvField("ST5872")).toBe('"ST5872"');
  });
});

describe("toCsv", () => {
  it("puts the licence and the caveats above the data", () => {
    const csv = toCsv(ROWS, OPTIONS);
    const lines = csv.split("\r\n");
    expect(lines[0]).toContain("Adder");
    expect(csv).toContain("Bristol Regional Environmental Records Centre");
    expect(csv).toContain("generalised");
    expect(csv).toContain("recording effort, not abundance");
    // The caveats travel with the file, because the file leaves the page that explained it.
    expect(csv.indexOf("generalised")).toBeLessThan(csv.indexOf("ST5872"));
  });

  it("writes one row per cell, with CRLF endings", () => {
    const csv = toCsv(ROWS, OPTIONS);
    expect(csv.endsWith("\r\n")).toBe(true);
    expect(csv).toContain('"ST5872","1000","12","9"');
    // A withheld verified count is empty, never zero: zero would be a claim.
    expect(csv).toContain('"ST5972","1000","3",');
  });

  it("omits the verified column entirely when the release does not publish it", () => {
    const csv = toCsv(ROWS, { ...OPTIONS, verificationAvailable: false });
    expect(csv).not.toContain("Verified");
    expect(csv).toContain('"ST5872","1000","12"\r\n');
  });

  it("carries no column the map does not already show", () => {
    // The export must not become a side channel: no coordinates, no recorder, no dates.
    const csv = toCsv(ROWS, OPTIONS).toLowerCase();
    for (const forbidden of ["easting", "northing", "latitude", "longitude", "recorder", "unique_no", "bliss"]) {
      expect(csv).not.toContain(forbidden);
    }
  });

  it("produces only the header block for an empty selection", () => {
    const csv = toCsv([], OPTIONS);
    expect(csv).toContain("Grid square");
    expect(csv.split("\r\n").filter((line) => line.startsWith('"ST'))).toHaveLength(0);
  });
});

describe("csvFilename", () => {
  it("slugifies the species name", () => {
    expect(csvFilename("Adder")).toBe("brerc-adder-grid-squares.csv");
    expect(csvFilename("Great Crested Newt")).toBe("brerc-great-crested-newt-grid-squares.csv");
  });

  it("never produces a path or a hidden file from a hostile name", () => {
    for (const name of ["../../etc/passwd", ".hidden", "a/b\\c", ""]) {
      const filename = csvFilename(name);
      expect(filename).toMatch(/^brerc-[a-z0-9-]*grid-squares\.csv$/);
      expect(filename).not.toContain("/");
      expect(filename).not.toContain("\\");
      expect(filename).not.toContain("..");
    }
  });
});
