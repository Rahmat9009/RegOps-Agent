// Panel.tsx — A titled section. Uses a real <section> with an accessible name so
// the page has a navigable landmark structure.

import { useId } from "react";
import type { LucideIcon } from "lucide-react";

export interface PanelProps {
  title: string;
  icon?: LucideIcon;
  description?: string;
  actions?: React.ReactNode;
  /** Remove body padding, e.g. for a full-bleed table. */
  flush?: boolean;
  children: React.ReactNode;
}

export function Panel({
  title,
  icon: Icon,
  description,
  actions,
  flush = false,
  children,
}: PanelProps) {
  const headingId = useId();

  return (
    <section className="panel" aria-labelledby={headingId}>
      <div className="panel__head">
        <h2 className="panel__title" id={headingId}>
          {Icon ? <Icon size={17} aria-hidden="true" /> : null}
          {title}
        </h2>
        {actions ? <div className="panel__actions">{actions}</div> : null}
        {description ? <p className="panel__desc">{description}</p> : null}
      </div>
      <div className={flush ? "panel__body panel__body--flush" : "panel__body"}>{children}</div>
    </section>
  );
}
