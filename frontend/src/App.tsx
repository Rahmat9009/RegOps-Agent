import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { ApprovalPage } from "@/routes/ApprovalPage";
import { AuditPage } from "@/routes/AuditPage";
import { CounterfactualPage } from "@/routes/CounterfactualPage";
import { DashboardPage } from "@/routes/DashboardPage";
import { EvidenceDetailPage } from "@/routes/EvidenceDetailPage";
import { FindingsPage } from "@/routes/FindingsPage";
import { IntakePage } from "@/routes/IntakePage";
import { NotFoundPage } from "@/routes/NotFoundPage";
import { RunDetailPage } from "@/routes/RunDetailPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="intake" element={<IntakePage />} />
          <Route path="runs/:runId" element={<RunDetailPage />} />
          <Route path="runs/:runId/findings" element={<FindingsPage />} />
          <Route path="runs/:runId/audit" element={<AuditPage />} />
          <Route path="findings/:findingId" element={<EvidenceDetailPage />} />
          <Route path="actions/:actionId/preview" element={<CounterfactualPage />} />
          <Route path="approvals/:approvalId" element={<ApprovalPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
