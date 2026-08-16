// AppShell.tsx — Persistent frame: navigation, the synthetic-data disclosure, and
// the landmark structure (banner / navigation / main / contentinfo).

import { NavLink, Outlet } from "react-router-dom";
import {
  FileCheck2,
  FlaskConical,
  Gauge,
  ListFilter,
  Radar,
  ShieldAlert,
  Upload,
  type LucideIcon,
} from "lucide-react";

import { API_MODE, SYNTHETIC_NOTICE } from "@/lib/api";
import { getActiveRunId } from "@/lib/activeRun";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Requires an active run id to be meaningful. */
  needsRun?: boolean;
}

export function AppShell() {
  // Read at render time so navigation reflects the run created moments ago.
  const runId = getActiveRunId();

  const primary: NavItem[] = [
    { to: "/", label: "Operations dashboard", icon: Gauge },
    { to: "/intake", label: "Regulation intake", icon: Upload },
  ];

  const runScoped: NavItem[] = [
    { to: runId ? `/runs/${runId}` : "#", label: "Run detail", icon: Radar, needsRun: true },
    {
      to: runId ? `/runs/${runId}/findings` : "#",
      label: "Findings",
      icon: ListFilter,
      needsRun: true,
    },
    {
      to: runId ? `/runs/${runId}/audit` : "#",
      label: "Audit report",
      icon: FileCheck2,
      needsRun: true,
    },
  ];

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <header className="shell__sidebar">
        <NavLink to="/" className="brand">
          <span className="brand__mark" aria-hidden="true">
            <ShieldAlert size={18} />
          </span>
          <span>
            <span className="brand__name">RegOps</span>
            <span className="brand__sub">Regulatory operations</span>
          </span>
        </NavLink>

        <nav aria-label="Primary">
          <ul className="nav">
            {primary.map((item) => (
              <NavItemLink key={item.to} item={item} disabled={false} />
            ))}
            <li className="nav__section" aria-hidden="true">
              Current run
            </li>
            {runScoped.map((item) => (
              <NavItemLink key={item.label} item={item} disabled={!runId} />
            ))}
          </ul>
        </nav>

        <div className="shell__foot">
          <p>
            RegOps identifies potential conflicts and supports review. It does not determine legal
            compliance.
          </p>
          <p>
            Data source: <span className="mono">{API_MODE}</span> adapter
          </p>
        </div>
      </header>

      <div className="shell__main">
        <p className="synthetic-banner">
          <FlaskConical size={16} aria-hidden="true" />
          <span>
            <strong>Synthetic demonstration.</strong> {SYNTHETIC_NOTICE}
          </span>
          <span className="synthetic-banner__mode">
            {API_MODE === "mock" ? "mock adapter" : "live API"}
          </span>
        </p>

        <main id="main" className="page" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function NavItemLink({ item, disabled }: { item: NavItem; disabled: boolean }) {
  const Icon = item.icon;

  if (disabled) {
    return (
      <li>
        <span className="nav__link" aria-disabled="true" title="Start a run first">
          <Icon size={16} className="nav__icon" aria-hidden="true" />
          {item.label}
        </span>
      </li>
    );
  }

  return (
    <li>
      <NavLink to={item.to} end={item.to === "/"} className="nav__link">
        <Icon size={16} className="nav__icon" aria-hidden="true" />
        {item.label}
      </NavLink>
    </li>
  );
}
