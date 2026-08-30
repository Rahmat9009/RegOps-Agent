# Phase 1 acceptance test (must pass before scale)

The vertical path must work end to end on **one document** before Phase 2 begins.

The hosted minimum slice passed this business outcome on 2026-08-30 with synthetic
run `011188a0-08c3-4bdc-864f-f90f415ca959`. The deployed orchestration differs from
the earlier callback design: Google Workflows performs one authenticated worker
invocation and returns after the run reaches `AWAITING_APPROVAL`; the run pauses in
authoritative Firestore state until the human decision reaches the existing API.

1. User uploads a regulation.
2. Gemini extracts one obligation with an exact citation.
3. The system finds one conflicting synthetic contract.
4. The evidence chain appears in Firestore and on the dashboard.
5. RegOps automatically creates an internal review task.
6. RegOps generates a proposed amendment (against the contract's shadow copy).
7. The run pauses outside agent authority for a human decision. The hosted minimum
   slice persists `AWAITING_APPROVAL`; it does not keep a Workflow callback open.
8. User approves.
9. The amendment is applied to the shadow copy.
10. The validation pipeline runs again.
11. The finding becomes `RESOLVED`.
12. An audit record is generated.

If this works on one document, the project is an agentic product. Everything after is scaling, hardening, and presentation.

The live proof resolved one finding, stored one `APPROVED_DRAFT`, reported zero
remaining findings, and produced a downloadable private audit package. This proves
only the exact synthetic fixture profile documented in
[`docs/live-deployment-evidence.md`](live-deployment-evidence.md), not general legal
or regulatory analysis.
