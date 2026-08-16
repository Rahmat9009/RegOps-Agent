// states.tsx — Loading, empty, error and recoverable-failure blocks.
//
// Every screen uses these so the four hard states are as designed as the happy
// path. Error copy is driven by RegOpsApiError.kind, so a 404, a 422 and a lost
// connection each read differently and offer the right next step.

import { Link } from "react-router-dom";
import {
  FileQuestion,
  Hourglass,
  Inbox,
  Loader2,
  OctagonAlert,
  RefreshCw,
  SearchX,
  ServerCrash,
  Wifi,
  type LucideIcon,
} from "lucide-react";

import type { RegOpsApiError } from "@/lib/api";

/* --------------------------------------------------------------- loading */

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state-block" role="status">
      <span className="state-block__icon state-block__icon--info">
        <Loader2 size={20} aria-hidden="true" className="spin" />
      </span>
      <span className="state-block__title">{label}</span>
    </div>
  );
}

/** Placeholder rows that match the shape of the content being loaded. */
export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack stack--tight" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton" style={{ height: "2.5rem" }} />
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------- empty */

export interface EmptyStateProps {
  title: string;
  children?: React.ReactNode;
  icon?: LucideIcon;
  action?: React.ReactNode;
}

export function EmptyState({ title, children, icon: Icon = Inbox, action }: EmptyStateProps) {
  return (
    <div className="state-block">
      <span className="state-block__icon">
        <Icon size={20} aria-hidden="true" />
      </span>
      <span className="state-block__title">{title}</span>
      {children ? <p className="state-block__text">{children}</p> : null}
      {action}
    </div>
  );
}

/** Distinct from EmptyState: there IS data, the filters just exclude all of it. */
export function NoResultsState({ onClear }: { onClear?: () => void }) {
  return (
    <EmptyState
      icon={SearchX}
      title="No findings match these filters"
      action={
        onClear ? (
          <button type="button" className="btn btn--sm" onClick={onClear}>
            Clear filters
          </button>
        ) : undefined
      }
    >
      Widen the severity filter or clear the search term to see the full list.
    </EmptyState>
  );
}

/* ----------------------------------------------------------------- error */

interface ErrorPresentation {
  icon: LucideIcon;
  tone: "critical" | "review" | "info";
  title: string;
  guidance: string;
  canRetry: boolean;
}

function presentError(error: RegOpsApiError): ErrorPresentation {
  switch (error.kind) {
    case "not_found":
      return {
        icon: FileQuestion,
        tone: "review",
        title: "Not found",
        guidance:
          "The record does not exist, or the run it belonged to is no longer available. Start a new analysis from regulation intake.",
        canRetry: false,
      };
    case "validation":
      return {
        icon: OctagonAlert,
        tone: "critical",
        title: "The request was rejected",
        guidance: "Correct the highlighted input and submit again.",
        canRetry: false,
      };
    case "conflict":
      return {
        icon: Hourglass,
        tone: "review",
        title: "Already decided",
        guidance: "Someone recorded a decision for this item first. Reload to see the outcome.",
        canRetry: true,
      };
    case "not_implemented":
      return {
        icon: Hourglass,
        tone: "info",
        title: "Not available yet",
        guidance:
          "This operation is declared in the API contract but begins in a later phase. There is nothing to retry.",
        canRetry: false,
      };
    case "network":
      return {
        icon: Wifi,
        tone: "critical",
        title: "Cannot reach the RegOps API",
        guidance: "Check the connection to the API and try again.",
        canRetry: true,
      };
    case "server":
      return {
        icon: ServerCrash,
        tone: "critical",
        title: "The RegOps API failed",
        guidance: "The server returned an error. Retrying is usually safe.",
        canRetry: true,
      };
    default:
      return {
        icon: OctagonAlert,
        tone: "critical",
        title: "Something went wrong",
        guidance: "Try again. If it keeps happening, the run may need to be restarted.",
        canRetry: true,
      };
  }
}

export interface ErrorStateProps {
  error: RegOpsApiError;
  onRetry?: () => void;
  /** Offer a way out when retrying will not help. */
  fallbackHref?: string;
  fallbackLabel?: string;
}

export function ErrorState({
  error,
  onRetry,
  fallbackHref = "/intake",
  fallbackLabel = "Go to regulation intake",
}: ErrorStateProps) {
  const presentation = presentError(error);
  const Icon = presentation.icon;

  return (
    <div className="state-block" role="alert">
      <span className={`state-block__icon state-block__icon--${presentation.tone}`}>
        <Icon size={20} aria-hidden="true" />
      </span>
      <span className="state-block__title">{presentation.title}</span>
      <p className="state-block__text">{error.message}</p>
      <p className="state-block__text">{presentation.guidance}</p>

      {error.details.length > 0 ? (
        <ul className="state-block__detail">
          {error.details.map((detail, index) => (
            <li key={index}>
              {detail.location && detail.location.length > 0
                ? `${detail.location.join(" → ")}: `
                : ""}
              {detail.message}
            </li>
          ))}
        </ul>
      ) : null}

      <p className="state-block__detail">
        {error.code}
        {error.status ? ` · HTTP ${error.status}` : ""}
      </p>

      <div className="row">
        {presentation.canRetry && onRetry ? (
          <button type="button" className="btn btn--primary" onClick={onRetry}>
            <RefreshCw size={15} aria-hidden="true" />
            Try again
          </button>
        ) : null}
        <Link className="btn" to={fallbackHref}>
          {fallbackLabel}
        </Link>
      </div>
    </div>
  );
}
