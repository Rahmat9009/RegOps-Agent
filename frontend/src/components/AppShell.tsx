// AppShell.tsx — Persistent frame: navigation, the synthetic-data disclosure, the
// live run presence, and the landmark structure (banner / navigation / main /
// contentinfo).
//
// The shell reads the current run from `RunPresenceContext`, which the screens'
// existing 2-second poll publishes into. The shell issues no request of its own.

import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import {
  FileCheck2,
  FlaskConical,
  Gauge,
  ListFilter,
  Radar,
  Upload,
  type LucideIcon,
} from "lucide-react";

import { API_MODE, SYNTHETIC_NOTICE, type Run } from "@/lib/api";
import { getActiveRunId } from "@/lib/activeRun";
import { formatPercent } from "@/lib/format";
import { RUN_STATE } from "@/lib/presentation";
import { RunPresenceContext, useRunPresence } from "@/hooks/useRunPresence";
import { RegOpsLockup } from "@/components/Logo";
import { PageTransition } from "@/components/PageTransition";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Requires an active run id to be meaningful. */
  needsRun?: boolean;
}

export function AppShell() {
  // Published by `useRunPolling`; never fetched here.
  const [presentRun, setPresentRun] = useState<Run | null>(null);

  return (
    <RunPresenceContext.Provider value={{ run: presentRun, publish: setPresentRun }}>
      <div className="shell">
        <a className="skip-link" href="#main">
          Skip to main content
        </a>

        <ConsoleSidebar />

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
            <PageTransition>
              <Outlet />
            </PageTransition>
          </main>
        </div>
      </div>
    </RunPresenceContext.Provider>
  );
}

function ConsoleSidebar() {
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
    <header className="shell__sidebar">
      <NavLink to="/" className="brand">
        <RegOpsLockup />
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

      <RunPresenceChip />

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
  );
}

/**
 * The run in flight, always visible in the chrome. Shows only what the polled
 * run actually reported; when no screen has polled a run yet there is nothing
 * here to show and the block is omitted rather than filled with a placeholder.
 */
function RunPresenceChip() {
  const { run } = useRunPresence();
  if (!run) return null;

  const descriptor = RUN_STATE[run.state];
  const Icon = descriptor.icon;
  const percent = Math.max(0, Math.min(100, run.progress.percent));

  return (
    <Link className="runchip" to={`/runs/${run.run_id}`}>
      <span className="runchip__head">
        <Radar size={12} aria-hidden="true" />
        Run in view
      </span>
      <span className="runchip__id">{run.run_id}</span>
      <span className="runchip__state">
        <Icon
          size={14}
          aria-hidden="true"
          className={descriptor.active === true ? "spin" : undefined}
        />
        {descriptor.label}
      </span>
      <span className="runchip__track" aria-hidden="true">
        <span className="runchip__fill" style={{ width: `${percent}%` }} />
      </span>
      <span className="sr-only">
        {`${formatPercent(percent)} of documents processed. Open run detail.`}
      </span>
    </Link>
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
