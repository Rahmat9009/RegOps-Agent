// PipelineMap.tsx — The lifecycle rail.
//
// The processing stages a run moves through, drawn as a track with a node per
// stage and the current one marked. Rendered as an ordered list so the sequence
// is conveyed structurally, and every node carries its stage name plus an
// explicit "complete / current stage / not started" string for screen readers:
// the fill colour is never the only thing saying where the run is.
//
// The rail turns from horizontal to vertical below 1280px — eleven stages side
// by side stop being readable long before mobile.

import { Check } from "lucide-react";

import type { RunState } from "@/lib/api";
import { PIPELINE_STEPS, RUN_STATE } from "@/lib/presentation";

export function PipelineMap({ current }: { current: RunState }) {
  // FAILED_RECOVERABLE and FAILED are not steps on the happy path; while a run is
  // in one of them the last completed step stays marked as current.
  const anchor: RunState = PIPELINE_STEPS.includes(current) ? current : "MAPPING";
  const currentIndex = PIPELINE_STEPS.indexOf(anchor);
  const descriptor = RUN_STATE[current];

  return (
    <ol className="rail">
      {PIPELINE_STEPS.map((step, index) => {
        const stepDescriptor = RUN_STATE[step];
        const isCurrent = index === currentIndex;
        const isDone = index < currentIndex;

        let className = "rail__step";
        if (isDone) className += " rail__step--done";
        if (isCurrent && current === "FAILED_RECOVERABLE") className += " rail__step--failed";
        else if (isCurrent && descriptor.tone === "review") className += " rail__step--review";
        // A finished run's last node is a completion, not a stage in flight.
        else if (isCurrent && descriptor.tone === "verified") className += " rail__step--done";
        else if (isCurrent) className += " rail__step--current";

        const Icon = isDone ? Check : stepDescriptor.icon;

        // The node pulses only while the pipeline is genuinely working. A run
        // parked on a decision, finished or failed sits still.
        const working = isCurrent && descriptor.active === true;

        return (
          <li key={step} className={className} aria-current={isCurrent ? "step" : undefined}>
            <span
              className={working ? "rail__node rail__node--working" : "rail__node"}
              aria-hidden="true"
            >
              <Icon size={14} className={working && stepDescriptor.active ? "spin" : undefined} />
            </span>
            <span className="rail__label">
              {stepDescriptor.label}
              <span className="sr-only">
                {isDone ? " — complete" : isCurrent ? " — current stage" : " — not started"}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
