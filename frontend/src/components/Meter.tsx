// Meter.tsx — Progress and score bars. Each carries its numeric value as text and
// exposes proper ARIA progressbar semantics; the bar itself is decoration.

import { motion, useReducedMotion } from "framer-motion";

import { formatPercent, formatRatio } from "@/lib/format";
import type { Tone } from "@/lib/presentation";

const FILL_CLASS: Partial<Record<Tone, string>> = {
  verified: "meter__fill--verified",
  review: "meter__fill--review",
  critical: "meter__fill--critical",
};

export interface ProgressMeterProps {
  label: string;
  /** 0..100 */
  percent: number;
  /** Text shown on the right, e.g. "148 / 300 documents". */
  detail?: string;
  tone?: Tone;
}

export function ProgressMeter({ label, percent, detail, tone = "info" }: ProgressMeterProps) {
  const clamped = Math.max(0, Math.min(100, percent));
  const reduceMotion = useReducedMotion();

  return (
    <div className="meter">
      <div className="meter__head">
        <span className="meter__label">{label}</span>
        <span className="meter__value">{detail ?? formatPercent(clamped)}</span>
      </div>
      <div
        className="meter__track"
        role="progressbar"
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${formatPercent(clamped)}`}
      >
        {/* Motion here shows that progress moved between polls, which a static
            bar cannot convey. Disabled when the reader prefers reduced motion. */}
        <motion.div
          className={["meter__fill", FILL_CLASS[tone] ?? ""].filter(Boolean).join(" ")}
          initial={false}
          animate={{ width: `${clamped}%` }}
          transition={reduceMotion ? { duration: 0 } : { duration: 0.45, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}

export interface ScoreMeterProps {
  label: string;
  /** 0..1 */
  value: number;
  description?: string;
  tone?: Tone;
}

export function ScoreMeter({ label, value, description, tone = "info" }: ScoreMeterProps) {
  const percent = Math.max(0, Math.min(1, value)) * 100;

  return (
    <div className="meter">
      <div className="meter__head">
        <span className="meter__label">{label}</span>
        <span className="meter__value">{formatRatio(value)}</span>
      </div>
      <div
        className="meter__track"
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${formatRatio(value)}`}
      >
        <div
          className={["meter__fill", FILL_CLASS[tone] ?? ""].filter(Boolean).join(" ")}
          style={{ width: `${percent}%` }}
        />
      </div>
      {description ? <p className="field__hint">{description}</p> : null}
    </div>
  );
}

export interface StatProps {
  label: string;
  value: string;
  note?: string;
  tone?: Tone;
  icon?: React.ReactNode;
}

export function Stat({ label, value, note, tone = "neutral", icon }: StatProps) {
  const toneClass =
    tone === "critical"
      ? "stat--critical"
      : tone === "review"
        ? "stat--review"
        : tone === "verified"
          ? "stat--verified"
          : "";

  return (
    <div className={["stat", toneClass].filter(Boolean).join(" ")}>
      <span className="stat__label">
        {icon}
        {label}
      </span>
      <span className="stat__value">{value}</span>
      {note ? <span className="stat__note">{note}</span> : null}
    </div>
  );
}
