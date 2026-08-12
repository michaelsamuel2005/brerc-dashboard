// ---------------------------------------------------------------------------
// `verified` verdict classification — the shared corpus.
//
// This table is duplicated, case for case, in api/etl/test_verified_parity.py.
// The server normalises before sending and the client normalises again, so the
// two implementations must agree exactly or the same record reads differently
// depending on which side you ask. If you change one table, change the other.
//
// The previous client implementation was a substring search:
//
//     if (s.includes("reject")) return "rejected";
//     ...
//     if (s.includes("accept")) return "accepted";
//
// "Not accepted" contains "accept" and no "reject", so it was classified
// ACCEPTED. Measured against this corpus that implementation produced 10 false
// accepts and returned "unknown" for 26 legible verdicts.
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { normaliseVerified } from "./schemas";

type Verdict = "accepted" | "unconfirmed" | "rejected" | "unknown";

/** Negating ACCEPTANCE is a rejection. This is the case the old code inverted. */
const NEGATED_ACCEPTANCE: Array<[string, Verdict]> = [
    ["Not accepted", "rejected"],
    ["not accepted", "rejected"],
    ["NOT ACCEPTED", "rejected"],
    ["un-accepted", "rejected"],
    ["unaccepted", "rejected"],
    ["never accepted", "rejected"],
    ["has not been accepted", "rejected"],
    ["non-accepted", "rejected"],
    ["disaccepted", "rejected"],
    ["verified - not accepted", "rejected"],
];

const REJECTED: Array<[string, Verdict]> = [
    ["Rejected", "rejected"],
    ["Rejected – not accepted", "rejected"],
    ["rejected (was accepted in error)", "rejected"],
    ["REJECTED - incorrect determination", "rejected"],
    ["Refused", "rejected"],
    ["Declined", "rejected"],
    ["Incorrect", "rejected"],
    ["Invalid record", "rejected"],
    ["Erroneous", "rejected"],
    ["Accepted then rejected", "rejected"],
];

/** Negating VERIFICATION means it has not been done yet — not that it failed. */
const UNCONFIRMED: Array<[string, Verdict]> = [
    ["Unconfirmed", "unconfirmed"],
    ["unconfirmed record", "unconfirmed"],
    ["Not verified", "unconfirmed"],
    ["not verified", "unconfirmed"],
    ["unverified", "unconfirmed"],
    ["Un-verified", "unconfirmed"],
    ["never verified", "unconfirmed"],
    ["has not been verified", "unconfirmed"],
    ["Not confirmed", "unconfirmed"],
    ["unconfirmed", "unconfirmed"],
    ["Not checked", "unconfirmed"],
    ["unchecked", "unconfirmed"],
    ["Provisional", "unconfirmed"],
    ["Uncertain", "unconfirmed"],
    ["Pending", "unconfirmed"],
    ["Pending review", "unconfirmed"],
    ["Awaiting verification", "unconfirmed"],
    ["awaiting determination", "unconfirmed"],
    ["Needs verification", "unconfirmed"],
    ["needs confirmation", "unconfirmed"],
    ["need checking", "unconfirmed"],
    ["to be verified", "unconfirmed"],
    ["to be confirmed", "unconfirmed"],
    ["unconfirmed but accepted", "unconfirmed"],
];

const ACCEPTED: Array<[string, Verdict]> = [
    ["Accepted", "accepted"],
    ["Accepted - correct", "accepted"],
    ["Accepted – considered correct", "accepted"],
    ["accepted (BRERC)", "accepted"],
    ["Verified", "accepted"],
    ["verified by expert", "accepted"],
    ["Confirmed", "accepted"],
    ["Correct", "accepted"],
    ["Valid", "accepted"],
    ["Determined", "accepted"],
];

/** Real BRERC data contains values a parser cannot read. They must not count. */
const UNKNOWN: Array<[string, Verdict]> = [
    ["BRERC (1)", "unknown"],
    ["", "unknown"],
    ["   ", "unknown"],
    ["1", "unknown"],
    ["yes", "unknown"],
    ["no", "unknown"],
    ["n/a", "unknown"],
    ["?", "unknown"],
    ["unknown", "unknown"],
];

const ALL = [...NEGATED_ACCEPTANCE, ...REJECTED, ...UNCONFIRMED, ...ACCEPTED, ...UNKNOWN];

describe("normaliseVerified", () => {
  it.each(NEGATED_ACCEPTANCE)("a negated acceptance is a rejection: %j", (input, want) => {
    expect(normaliseVerified(input)).toBe(want);
  });

  it.each(REJECTED)("an active negative determination is a rejection: %j", (input, want) => {
    expect(normaliseVerified(input)).toBe(want);
  });

  it.each(UNCONFIRMED)("incomplete verification is unconfirmed, not rejected: %j", (input, want) => {
    expect(normaliseVerified(input)).toBe(want);
  });

  it.each(ACCEPTED)("a positive determination is accepted: %j", (input, want) => {
    expect(normaliseVerified(input)).toBe(want);
  });

  it.each(UNKNOWN)("an unreadable verdict is unknown, never accepted: %j", (input, want) => {
    expect(normaliseVerified(input)).toBe(want);
  });

  it("covers the whole shared corpus", () => {
    expect(ALL).toHaveLength(63);
  });

  it("NEVER reports accepted for anything carrying a negation", () => {
    // The single property that matters: a public map claims a verified record
    // has been checked by somebody. Reading a turned-down record as verified
    // breaks that claim, so this is asserted as a property, not case by case.
    for (const [input] of ALL) {
      if (/\b(?:not|non|never|un|dis)[\s-]*(?:been[\s-]+)?accept/i.test(input)) {
        expect(normaliseVerified(input)).not.toBe("accepted");
      }
    }
  });

  it("degrades rather than throwing on a malformed value", () => {
    // z.string() guarantees a string inside the schema, but the function is
    // exported and a malformed response should not crash the render.
    expect(normaliseVerified(undefined as unknown as string)).toBe("unknown");
    expect(normaliseVerified(null as unknown as string)).toBe("unknown");
    expect(normaliseVerified(42 as unknown as string)).toBe("unknown");
  });
});
