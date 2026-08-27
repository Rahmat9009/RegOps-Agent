# Synthetic worker evaluation assets

Both the PDF and XLSX workbook are entirely synthetic demonstration materials.
They represent no real regulation, agency, worker, contract, or case. The material
is not legal advice and must not be used for legal or operational decisions.

## Asset roles

- [`samples/regops-synthetic-regulation-2026.pdf`](../../samples/regops-synthetic-regulation-2026.pdf)
  is the input benchmark, with document ID **REG-2026-0417**.
- [`backend/evals/fixtures/`](../../backend/evals/fixtures/) contains the
  machine-readable canonical expectations consumed by backend tests.
- [`regops-ground-truth-evaluation.xlsx`](regops-ground-truth-evaluation.xlsx)
  is the judge/evaluator scorecard. It is not a runtime dependency or a substitute
  for the canonical JSON fixtures. Runtime tests must not parse or depend on XLSX.

The JSON expectations are 3 obligations and 37 findings: 6 high, 11 medium, and
20 low. Counterfactual expectations are a baseline of 37, 31 predicted resolved,
6 remaining, 2 new conflicts, and 1 remaining high-risk finding. These are benchmark
expectations, not measurements from an executed evaluation or shadow simulation.

Fixture provenance records the original Phase 1B.2A creation context, when the PDF
was under `sample/` and the workbook was not yet present. This asset-only cleanup
preserves those fixtures and both asset files' bytes; it does not reconcile or
regenerate expectations from the workbook.

## SHA-256 integrity

Hashes cover the exact file bytes, without normalization.

| Asset | SHA-256 |
| --- | --- |
| `samples/regops-synthetic-regulation-2026.pdf` | `6571084f3ff2215fcf48d467c7d9e8afd808f5f4b644c00ddca7a9ca66e4c5d9` |
| `docs/evaluation/regops-ground-truth-evaluation.xlsx` | `6253aacc28f3a959249c1b8f4d66cb3ea57137853d1ad58919b138ac8bb11731` |
