// RunInsights.tsx — Renders `Run.recovery` and `Run.change_detection`.
//
// Both are nullable in the contract, so each block states plainly when the API
// reported nothing rather than inventing a value. Only the safe fields the
// contract defines are shown: no prompts, stack traces, partition internals or
// other infrastructure detail is displayed, because none is returned.

import type { ChangeDetection, RecoveryInfo } from "@/lib/api";
import { formatCount, formatDateTime, pluralize } from "@/lib/format";
import {
  changeDetectionDescriptor,
  recoveryDescriptor,
  RUN_STATE,
  shortenHash,
} from "@/lib/presentation";
import { RefreshCw } from "lucide-react";

import { Mono, StatusBadge } from "@/components/Badge";

/**
 * A hash shortened for reading, with the complete value still available to
 * assistive technology and as a hover title.
 */
export function HashValue({ label, value }: { label: string; value: string }) {
  return (
    <span title={value}>
      <Mono>
        <span aria-hidden="true">{shortenHash(value)}</span>
      </Mono>
      <span className="sr-only">{`${label}: ${value}`}</span>
    </span>
  );
}

export function RecoveryDetails({ recovery }: { recovery: RecoveryInfo | null | undefined }) {
  if (!recovery) {
    return (
      <p className="field__hint">
        The API reported no recovery record for this run, so nothing is shown here.
      </p>
    );
  }

  const descriptor = recoveryDescriptor(recovery);

  // A checkpoint is the important part of a recovery record: it says the run did
  // not start over. It is called out plainly rather than alarmingly.
  const checkpointState = recovery.attempt_count > 0 ? recovery.checkpoint_state : null;

  return (
    <div className="stack stack--tight">
      <div className="chip-row">
        <StatusBadge descriptor={descriptor} srPrefix="Recovery:" />
      </div>
      <p className="field__hint">{descriptor.description}</p>
      {checkpointState ? (
        <p className="checkpoint">
          <RefreshCw size={15} aria-hidden="true" />
          <span>
            Resumed from the <strong>{RUN_STATE[checkpointState].label.toLowerCase()}</strong>{" "}
            checkpoint after {pluralize(recovery.attempt_count, "attempt")}. Work completed before
            the failure was not repeated.
          </span>
        </p>
      ) : null}
      <dl className="dl">
        <dt>Checkpoint</dt>
        <dd>
          {recovery.checkpoint_state ? (
            <StatusBadge
              descriptor={RUN_STATE[recovery.checkpoint_state]}
              srPrefix="Checkpoint state:"
            />
          ) : (
            "No checkpoint reported"
          )}
        </dd>
        <dt>Attempts</dt>
        <dd>{pluralize(recovery.attempt_count, "attempt")}</dd>
        <dt>Last error</dt>
        <dd>
          {recovery.last_error_code ? (
            <>
              <Mono>{recovery.last_error_code}</Mono>
              {recovery.last_error_message ? (
                <p className="field__hint">{recovery.last_error_message}</p>
              ) : null}
            </>
          ) : (
            "No error reported"
          )}
        </dd>
      </dl>
    </div>
  );
}

export function ChangeDetectionDetails({
  detection,
}: {
  detection: ChangeDetection | null | undefined;
}) {
  if (!detection) {
    return (
      <p className="field__hint">
        The API returned no change-detection result for this run, so this console does not report
        whether the document is new, changed or unchanged.
      </p>
    );
  }

  const descriptor = changeDetectionDescriptor(detection);

  return (
    <div className="stack stack--tight">
      <div className="chip-row">
        <StatusBadge descriptor={descriptor} srPrefix="Change detection:" />
      </div>
      <p className="field__hint">{descriptor.description}</p>
      <dl className="dl">
        <dt>Detected</dt>
        <dd>{formatDateTime(detection.detected_at)}</dd>
        <dt>Source hash</dt>
        <dd>
          <HashValue label="Source SHA-256" value={detection.source_sha256} />
        </dd>
        <dt>Previous hash</dt>
        <dd>
          {detection.previous_source_sha256 ? (
            <HashValue label="Previous source SHA-256" value={detection.previous_source_sha256} />
          ) : (
            "None recorded"
          )}
        </dd>
      </dl>
      <p className="field__hint">
        Hashes are shortened for reading; the full {formatCount(64)}-character value is available to
        screen readers and on hover.
      </p>
    </div>
  );
}
