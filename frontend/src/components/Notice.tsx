// Notice.tsx — Inline callout. Always icon + title + text, so the tone is legible
// without relying on colour.

import { AlertTriangle, CheckCircle2, Info, OctagonAlert, type LucideIcon } from "lucide-react";

import type { Tone } from "@/lib/presentation";

const TONE_ICON: Record<Tone, LucideIcon> = {
  neutral: Info,
  info: Info,
  review: AlertTriangle,
  critical: OctagonAlert,
  verified: CheckCircle2,
};

const TONE_CLASS: Record<Tone, string> = {
  neutral: "",
  info: "notice--info",
  review: "notice--review",
  critical: "notice--critical",
  verified: "notice--verified",
};

export interface NoticeProps {
  tone?: Tone;
  title?: string;
  icon?: LucideIcon;
  /** Announce to assistive technology when the notice appears. */
  live?: boolean;
  children: React.ReactNode;
}

export function Notice({ tone = "neutral", title, icon, live = false, children }: NoticeProps) {
  const Icon = icon ?? TONE_ICON[tone];
  const classes = ["notice", TONE_CLASS[tone]].filter(Boolean).join(" ");

  return (
    <div className={classes} role={live ? "status" : undefined}>
      <Icon size={17} aria-hidden="true" />
      <div>
        {title ? <strong className="notice__title">{title}</strong> : null}
        <div>{children}</div>
      </div>
    </div>
  );
}
