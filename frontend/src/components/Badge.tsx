// Badge.tsx — The single way a status is rendered anywhere in the console:
// icon + text + colour. Colour is never the only carrier of meaning.

import type { Descriptor, Tone } from "@/lib/presentation";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "",
  info: "badge--info",
  review: "badge--review",
  critical: "badge--critical",
  verified: "badge--verified",
};

export interface StatusBadgeProps {
  descriptor: Descriptor;
  /** Overrides the descriptor's label, e.g. to show a count alongside it. */
  label?: string;
  size?: "sm" | "lg";
  /** Rendered before the label for screen readers, e.g. "Severity:". */
  srPrefix?: string;
  /** Spin the icon while work is in progress. */
  animateIcon?: boolean;
}

export function StatusBadge({
  descriptor,
  label,
  size = "sm",
  srPrefix,
  animateIcon = false,
}: StatusBadgeProps) {
  const Icon = descriptor.icon;
  const classes = ["badge", TONE_CLASS[descriptor.tone], size === "lg" ? "badge--lg" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes}>
      <Icon
        size={size === "lg" ? 18 : 14}
        aria-hidden="true"
        className={animateIcon ? "spin" : undefined}
      />
      {srPrefix ? <span className="sr-only">{srPrefix} </span> : null}
      <span>{label ?? descriptor.label}</span>
    </span>
  );
}

export interface TagProps {
  children: React.ReactNode;
  icon?: Descriptor["icon"];
}

export function Tag({ children, icon: Icon }: TagProps) {
  return (
    <span className="tag">
      {Icon ? <Icon size={12} aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

export function Mono({ children }: { children: React.ReactNode }) {
  return <span className="mono">{children}</span>;
}
