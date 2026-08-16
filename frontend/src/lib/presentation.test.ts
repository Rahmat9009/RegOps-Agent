// Presentation of the two nullable Phase 1B blocks: Run.recovery and
// Run.change_detection. Every status must carry text, not colour alone, so these
// helpers always return a label, an icon and a description.

import { describe, expect, it } from "vitest";

import type { ChangeDetection, RecoveryInfo } from "@/lib/api";
import { changeDetectionDescriptor, recoveryDescriptor, shortenHash } from "./presentation";

function recovery(overrides: Partial<RecoveryInfo> = {}): RecoveryInfo {
  return {
    recovery_available: false,
    checkpoint_state: "MAPPING",
    attempt_count: 1,
    last_error_code: "partition_timeout",
    last_error_message: "A corpus partition exceeded its processing window.",
    ...overrides,
  };
}

function detection(overrides: Partial<ChangeDetection> = {}): ChangeDetection {
  return {
    source_sha256: "a".repeat(64),
    previous_source_sha256: "b".repeat(64),
    changed: true,
    detected_at: "2026-08-16T09:00:00.000Z",
    ...overrides,
  };
}

describe("recoveryDescriptor", () => {
  it("flags an outstanding recovery for review", () => {
    const descriptor = recoveryDescriptor(recovery({ recovery_available: true }));
    expect(descriptor.tone).toBe("review");
    expect(descriptor.label).toMatch(/recovery available/i);
    expect(descriptor.description).toMatch(/mapping/i);
  });

  it("reports a completed resume as verified", () => {
    const descriptor = recoveryDescriptor(recovery());
    expect(descriptor.tone).toBe("verified");
    expect(descriptor.label).toMatch(/recovered/i);
  });

  it("stays neutral when nothing was ever retried", () => {
    const descriptor = recoveryDescriptor(
      recovery({ attempt_count: 0, checkpoint_state: null, last_error_code: null }),
    );
    expect(descriptor.tone).toBe("neutral");
  });

  it("copes with a null checkpoint", () => {
    const descriptor = recoveryDescriptor(
      recovery({ recovery_available: true, checkpoint_state: null }),
    );
    expect(descriptor.description.length).toBeGreaterThan(0);
  });

  it("always carries a label, an icon and a description", () => {
    for (const value of [
      recovery({ recovery_available: true }),
      recovery(),
      recovery({ attempt_count: 0 }),
    ]) {
      const descriptor = recoveryDescriptor(value);
      expect(descriptor.label).toBeTruthy();
      expect(descriptor.icon).toBeTruthy();
      expect(descriptor.description).toBeTruthy();
    }
  });
});

describe("changeDetectionDescriptor", () => {
  it("distinguishes changed from unchanged", () => {
    expect(changeDetectionDescriptor(detection()).label).toMatch(/changed/i);
    expect(changeDetectionDescriptor(detection({ changed: false })).label).toMatch(/unchanged/i);
  });

  it("calls a document with no predecessor new", () => {
    const descriptor = changeDetectionDescriptor(detection({ previous_source_sha256: null }));
    expect(descriptor.label).toMatch(/new document/i);
  });

  it("always carries a label, an icon and a description", () => {
    for (const value of [
      detection(),
      detection({ changed: false }),
      detection({ previous_source_sha256: null }),
    ]) {
      const descriptor = changeDetectionDescriptor(value);
      expect(descriptor.label).toBeTruthy();
      expect(descriptor.icon).toBeTruthy();
      expect(descriptor.description).toBeTruthy();
    }
  });
});

describe("shortenHash", () => {
  it("shortens a 64-character digest for display", () => {
    const short = shortenHash("a".repeat(64));
    expect(short).toBe(`${"a".repeat(12)}…`);
  });

  it("leaves short values alone", () => {
    expect(shortenHash("abc")).toBe("abc");
    expect(shortenHash("a".repeat(12))).toBe("a".repeat(12));
  });

  it("honours a custom visible length", () => {
    expect(shortenHash("a".repeat(64), 4)).toBe("aaaa…");
  });
});
