# RegOps architecture (summary)

Full specs live in the delivered planning documents (Frozen Spec v3, Phase 1 Tech Spec). This is the in-repo summary.

## Four agent roles
1. **Change Detector** — hash + version diff; starts a run on a genuine change.
2. **Regulation Analyst** — Gemini structured extraction; obligations + dates + exceptions + page-level citations; refuses unsupported claims.
3. **Impact Investigator** — deterministic match over the corpus + internal refutation pass (survived/refuted/uncertain).
4. **Action Controller** — deterministic counterfactual (shadow copy) → auto low-risk actions / pause consequential ones for approval → execute idempotently → re-validate.

## Phase boundaries and services

- **Phase 0:** Python 3.12 FastAPI, OpenAPI contract, tests, and Cloud Run-ready container.
- **Phase 1:** the one-document workflow runs in one Cloud Run service process using Gemini 3.5 (Vertex AI), Google ADK, Firestore, Cloud Storage, and Google Workflows. It does not use Cloud Run Jobs or Pub/Sub.
- **Phase 2:** Cloud Run Jobs, partition checkpoints, and Pub/Sub begin. BigQuery, Memory Bank, and advanced monitoring remain deferred until justified.

## Run state machine
`INGESTED → EXTRACTING → EXTRACTED → MAPPING → MAPPED → VERIFYING → VERIFIED → AWAITING_APPROVAL → EXECUTING → REVALIDATING → COMPLETED` (+ `FAILED_RECOVERABLE`, `FAILED`).

## Evidence chain (linked Firestore records, no graph DB)
`Regulation → Obligation → Finding → Affected case → Proposed action`, each finding carrying page-level citations and five separate scores (evidence strength, source authority, interpretation confidence, operational severity, human-review-required).

## Integrity disclosure
Software is new (built Aug 3–31). Pre-Aug-3 domain knowledge is pre-existing source material. All contracts/cases are synthetic, generated during the hackathon, and labeled synthetic.
