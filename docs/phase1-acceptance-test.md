# Phase 1 acceptance test (must pass before scale)

The vertical path must work end to end on **one document** before Phase 2 begins.

1. User uploads a regulation.
2. Gemini extracts one obligation with an exact citation.
3. The system finds one conflicting synthetic contract.
4. The evidence chain appears in Firestore and on the dashboard.
5. RegOps automatically creates an internal review task.
6. RegOps generates a proposed amendment (against the contract's shadow copy).
7. The workflow pauses (Google Workflows callback).
8. User approves.
9. The amendment is applied to the shadow copy.
10. The validation pipeline runs again.
11. The finding becomes `RESOLVED`.
12. An audit record is generated.

If this works on one document, the project is an agentic product. Everything after is scaling, hardening, and presentation.
