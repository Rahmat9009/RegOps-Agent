// PageHeader.tsx — Title block with optional breadcrumbs and status slot.

import { Fragment } from "react";
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";

export interface Crumb {
  label: string;
  to?: string;
}

export interface PageHeaderProps {
  title: string;
  lede?: string;
  crumbs?: Crumb[];
  status?: React.ReactNode;
  actions?: React.ReactNode;
  /** A short label above the title naming what kind of screen this is. */
  eyebrow?: string;
}

export function PageHeader({ title, lede, crumbs, status, actions, eyebrow }: PageHeaderProps) {
  return (
    <header className="page__head">
      {crumbs && crumbs.length > 0 ? (
        <nav aria-label="Breadcrumb">
          <ol className="breadcrumbs">
            {crumbs.map((crumb, index) => (
              <Fragment key={`${crumb.label}-${index}`}>
                <li>
                  {crumb.to ? <Link to={crumb.to}>{crumb.label}</Link> : <span>{crumb.label}</span>}
                </li>
                {index < crumbs.length - 1 ? (
                  <li aria-hidden="true">
                    <ChevronRight size={13} />
                  </li>
                ) : null}
              </Fragment>
            ))}
          </ol>
        </nav>
      ) : null}

      {eyebrow && !crumbs ? <span className="eyebrow">{eyebrow}</span> : null}

      <div className="page__title-row">
        <h1>{title}</h1>
        {status}
        {actions ? <div className="panel__actions">{actions}</div> : null}
      </div>

      {lede ? <p className="page__lede">{lede}</p> : null}
    </header>
  );
}
