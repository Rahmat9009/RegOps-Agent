import { Link } from "react-router-dom";
import { Compass } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { EmptyState } from "@/components/states";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Panel title="Not found" icon={Compass}>
        <EmptyState
          icon={Compass}
          title="There is nothing at this address"
          action={
            <Link className="btn btn--primary" to="/">
              Go to the operations dashboard
            </Link>
          }
        >
          The link may be out of date, or the run it referred to may no longer exist.
        </EmptyState>
      </Panel>
    </>
  );
}
