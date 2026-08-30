// Logo.tsx — The RegOps mark.
//
// Concept: document → evidence chain → controlled decision.
//
// The stem and bowl draw an R and read as the record itself. The leg is the
// evidence chain leaving that record, and it terminates in a single filled node:
// the decision, which is the only part of the mark that is solid. Nothing else
// is added, so the whole thing still resolves at 16px.
//
// Both pieces inherit `currentColor`, so the mark works on the navy chrome, on a
// light surface and in dark mode without a second asset.

export interface MarkProps {
  size?: number;
  /** Colour of the decision node. Defaults to the current text colour. */
  accent?: string;
  className?: string;
}

export function RegOpsMark({ size = 32, accent, className }: MarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {/* The record: an R built from a stem and a half-round bowl. */}
      <path
        d="M8.8 23.5V7h6.9a4.5 4.5 0 0 1 0 9H8.8"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* The evidence chain leaving the record. */}
      <path
        d="M14.2 16 19.6 21.6"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      {/* The decision: the one solid element in the mark. */}
      <circle cx="22" cy="24" r="3.3" fill={accent ?? "currentColor"} />
    </svg>
  );
}

export interface LockupProps {
  /** Second line under the wordmark. Omit for the compact lockup. */
  subtitle?: string;
  markSize?: number;
}

/** The full horizontal lockup: tile + wordmark + descriptor. */
export function RegOpsLockup({ subtitle = "Regulatory operations", markSize = 23 }: LockupProps) {
  return (
    <>
      <span className="brand__tile" aria-hidden="true">
        <RegOpsMark size={markSize} accent="var(--chrome-accent)" />
      </span>
      <span>
        <span className="brand__name">RegOps</span>
        {subtitle ? <span className="brand__sub">{subtitle}</span> : null}
      </span>
    </>
  );
}
