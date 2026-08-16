import { describe, expect, it } from "vitest";

import {
  buildFindingsSearch,
  filterKey,
  FINDINGS_PAGE_SIZE,
  nextFindingsQuery,
  nextOffset,
  pageRange,
  parseOffset,
  previousOffset,
  readFindingsQuery,
} from "./pagination";

describe("readFindingsQuery", () => {
  it("reads severity, search and offset", () => {
    const query = readFindingsQuery(new URLSearchParams("severity=high&q=fee&offset=25"));
    expect(query).toEqual({ severity: "high", q: "fee", offset: 25 });
  });

  it("ignores an unknown severity", () => {
    expect(readFindingsQuery(new URLSearchParams("severity=urgent")).severity).toBe("");
  });

  it("defaults to the first page", () => {
    expect(readFindingsQuery(new URLSearchParams()).offset).toBe(0);
  });
});

describe("parseOffset", () => {
  it.each([
    [null, 0],
    ["", 0],
    ["-5", 0],
    ["abc", 0],
    ["0", 0],
    ["25", 25],
  ])("parses %s as %i", (input, expected) => {
    expect(parseOffset(input)).toBe(expected);
  });
});

describe("buildFindingsSearch", () => {
  it("omits defaults so a plain list has a clean URL", () => {
    expect(buildFindingsSearch({ severity: "", q: "", offset: 0 }).toString()).toBe("");
  });

  it("round-trips a filtered page", () => {
    const params = buildFindingsSearch({ severity: "medium", q: "placement fee", offset: 50 });
    expect(readFindingsQuery(params)).toEqual({
      severity: "medium",
      q: "placement fee",
      offset: 50,
    });
  });
});

describe("nextFindingsQuery", () => {
  const page3 = { severity: "high", q: "fee", offset: 50 } as const;

  it("resets the offset when the severity filter changes", () => {
    expect(nextFindingsQuery(page3, { severity: "low", q: "fee" }).offset).toBe(0);
  });

  it("resets the offset when the search term changes", () => {
    expect(nextFindingsQuery(page3, { severity: "high", q: "medical" }).offset).toBe(0);
  });

  it("resets the offset when filters are cleared", () => {
    expect(nextFindingsQuery(page3, { severity: "", q: "" }).offset).toBe(0);
  });

  it("keeps the offset while the filters are unchanged", () => {
    expect(nextFindingsQuery(page3, { severity: "high", q: "fee", offset: 75 }).offset).toBe(75);
  });

  it("treats the filter identity as severity plus search", () => {
    expect(filterKey({ severity: "high", q: "fee" })).toBe(filterKey({ severity: "high", q: "fee" }));
    expect(filterKey({ severity: "high", q: "fee" })).not.toBe(
      filterKey({ severity: "high", q: "fees" }),
    );
  });
});

describe("pageRange", () => {
  it("describes the visible slice of the filtered result", () => {
    expect(pageRange(0, 25, 37)).toEqual({
      first: 1,
      last: 25,
      total: 37,
      hasPrevious: false,
      hasNext: true,
    });
    expect(pageRange(25, 12, 37)).toEqual({
      first: 26,
      last: 37,
      total: 37,
      hasPrevious: true,
      hasNext: false,
    });
  });

  it("reports an empty range for an empty page", () => {
    expect(pageRange(0, 0, 0)).toEqual({
      first: 0,
      last: 0,
      total: 0,
      hasPrevious: false,
      hasNext: false,
    });
  });
});

describe("offset stepping", () => {
  it("never steps before the first page", () => {
    expect(previousOffset(0)).toBe(0);
    expect(previousOffset(10, 25)).toBe(0);
    expect(previousOffset(50, 25)).toBe(25);
  });

  it("never steps past the end of the filtered result", () => {
    expect(nextOffset(25, 25, 37)).toBe(25);
    expect(nextOffset(0, 25, 37)).toBe(25);
  });

  it("uses a page size inside the contract's 1-100 range", () => {
    expect(FINDINGS_PAGE_SIZE).toBeGreaterThanOrEqual(1);
    expect(FINDINGS_PAGE_SIZE).toBeLessThanOrEqual(100);
  });
});
