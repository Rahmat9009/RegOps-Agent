// Meter.tsx — Progress bars, score bars and metric tiles.
//
// Each carries its numeric value as text and exposes proper ARIA progressbar
// semantics; the bar itself is decoration that makes a column of numbers
// scannable. Nothing here is readable by colour alone.

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
          transition={reduceMotion ? { duration: 0 } : { duration: 0.4, ease: [0.2, 0, 0, 1] }}
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

export interface ScoreBarProps {
  /** Accessible name for the score, e.g. "Evidence strength". */
  label: string;
  /** 0..1 */
  value: number;
  /** Bars above this read as adequate; below it they are marked for review. */
  threshold?: number;
}

/**
 * The compact score used inside dense table cells. The percentage leads and is
 * the authoritative reading; the bar only lets a reader scan a column quickly.
 */
export function ScoreBar({ label, value, threshold = 0.7 }: ScoreBarProps) {
  const percent = Math.max(0, Math.min(1, value)) * 100;
  const low = value < threshold;

  return (
    <span className="score">
      <span className="score__value">{formatRatio(value)}</span>
      <span
        className="score__track"
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${formatRatio(value)}`}
      >
        <span
          className={low ? "score__fill score__fill--review" : "score__fill"}
          style={{ width: `${percent}%` }}
        />
      </span>
    </span>
  );
}

export interface StatProps {
  label: string;
  value: string;
  note?: string;
  tone?: Tone;
  icon?: React.ReactNode;
  /** Position in its group, used only for a short entrance stagger. */
  index?: number;
}

const TONE_STAT: Partial<Record<Tone, string>> = {
  info: "stat--info",
  critical: "stat--critical",
  review: "stat--review",
  verified: "stat--verified",
};

export function Stat({ label, value, note, tone = "neutral", icon, index = 0 }: StatProps) {
  const reduceMotion = useReducedMotion();
  // A short stagger over a small group reads as the metrics landing together.
  // Anything past the sixth tile appears with the sixth.
  const delay = reduceMotion ? 0 : Math.min(index, 5) * 0.04;

  return (
    <motion.div
      className={["stat", TONE_STAT[tone] ?? ""].filter(Boolean).join(" ")}
      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.2, 0, 0, 1], delay }}
    >
      <span className="stat__label">
        {icon}
        {label}
      </span>
      <span className="stat__value">{value}</span>
      {note ? <span className="stat__note">{note}</span> : null}
    </motion.div>
  );
}
