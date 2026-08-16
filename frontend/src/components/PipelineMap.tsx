// PipelineMap.tsx — The processing stages a run moves through, with the current
// one marked. Rendered as an ordered list so the sequence is conveyed structurally
// and not only visually.

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
    <ol className="pipeline">
      {PIPELINE_STEPS.map((step, index) => {
        const stepDescriptor = RUN_STATE[step];
        const isCurrent = index === currentIndex;
        const isDone = index < currentIndex;

        let className = "pipeline__step";
        if (isDone) className += " pipeline__step--done";
        if (isCurrent && current === "FAILED_RECOVERABLE") className += " pipeline__step--failed";
        else if (isCurrent && descriptor.tone === "review") className += " pipeline__step--review";
        else if (isCurrent) className += " pipeline__step--current";

        const Icon = isDone ? Check : stepDescriptor.icon;

        return (
          <li
            key={step}
            className={className}
            aria-current={isCurrent ? "step" : undefined}
          >
            <Icon
              size={14}
              aria-hidden="true"
              className={isCurrent && stepDescriptor.active ? "spin" : undefined}
            />
            <span>{stepDescriptor.label}</span>
            <span className="sr-only">
              {isDone ? " — complete" : isCurrent ? " — current stage" : " — not started"}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
