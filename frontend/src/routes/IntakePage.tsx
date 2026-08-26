// IntakePage — View 2: regulation intake.
//
// Upload a synthetic regulation PDF, acknowledge that the document is synthetic,
// confirm, and start the analysis. `POST /api/v1/runs` is multipart/form-data and
// requires both `regulation_file` and `synthetic_ack`.

import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  CheckCircle2,
  FileDiff,
  FileText,
  FlaskConical,
  Loader2,
  Upload,
  X,
} from "lucide-react";

import { api, toRegOpsApiError, type RegOpsApiError, type Run } from "@/lib/api";
import { setActiveRunId } from "@/lib/activeRun";
import { formatBytes, formatDateTime } from "@/lib/format";
import { RUN_STATE } from "@/lib/presentation";
import { Mono, StatusBadge, Tag } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { ChangeDetectionDetails } from "@/components/RunInsights";

/**
 * A minimal placeholder PDF so the workflow can be demonstrated without hunting
 * for a file. It is explicitly labelled as a synthetic stand-in, not a regulation.
 */
function syntheticSampleFile(): File {
  const pdf = [
    "%PDF-1.4",
    "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
    "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj",
    "trailer<</Root 1 0 R>>",
    "%%EOF",
  ].join("\n");

  return new File([pdf], "synthetic-fee-rule-amendment.pdf", { type: "application/pdf" });
}

export function IntakePage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [ack, setAck] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<RegOpsApiError | null>(null);
  const [accepted, setAccepted] = useState<Run | null>(null);

  const canSubmit = file !== null && ack && !submitting;

  function chooseFile(next: File | null): void {
    setFile(next);
    setError(null);
  }

  async function handleSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (!file) return;

    setSubmitting(true);
    setError(null);
    try {
      const run = await api.createRun({ regulation_file: file, synthetic_ack: ack });
      setActiveRunId(run.run_id);
      setAccepted(run);
    } catch (cause: unknown) {
      setError(toRegOpsApiError(cause));
    } finally {
      setSubmitting(false);
    }
  }

  if (accepted) {
    return <AcceptedRun run={accepted} onStartAnother={() => setAccepted(null)} />;
  }

  return (
    <>
      <PageHeader
        title="Regulation intake"
        lede="Upload a synthetic regulation document to start an analysis run. RegOps identifies potential conflicts across a synthetic corpus and supports human review; it does not determine legal compliance."
        crumbs={[{ label: "Operations", to: "/" }, { label: "Regulation intake" }]}
      />

      <Notice tone="review" title="Synthetic documents only" icon={FlaskConical}>
        Upload only synthetic demonstration documents. Do not upload real regulations, real
        contracts, or any document containing personal data. Every record produced by this run is
        labelled synthetic.
      </Notice>

      <form onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className="stack">
          <Panel
            title="Regulation document"
            icon={Upload}
            description="PDF only. The file is sent to POST /api/v1/runs as multipart form data."
          >
            <div className="stack">
              {file ? (
                <div className="filecard">
                  <FileText size={20} aria-hidden="true" />
                  <span className="filecard__meta">
                    <span className="filecard__name">{file.name}</span>
                    <span className="filecard__size">
                      {formatBytes(file.size)} · {file.type || "unknown type"}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="btn btn--sm"
                    onClick={() => {
                      chooseFile(null);
                      if (inputRef.current) inputRef.current.value = "";
                    }}
                  >
                    <X size={14} aria-hidden="true" />
                    Remove
                  </button>
                </div>
              ) : (
                <div
                  className={dragging ? "dropzone dropzone--active" : "dropzone"}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragging(false);
                    const dropped = event.dataTransfer.files[0];
                    if (dropped) chooseFile(dropped);
                  }}
                  onClick={() => inputRef.current?.click()}
                >
                  <Upload size={24} aria-hidden="true" />
                  <span>Drag a PDF here, or choose a file</span>
                  <span className="dropzone__hint">
                    Nothing is uploaded until you confirm and start the analysis.
                  </span>
                </div>
              )}

              <div className="field">
                <label className="field__label" htmlFor="regulation-file">
                  Regulation PDF
                </label>
                <input
                  ref={inputRef}
                  id="regulation-file"
                  className="input"
                  type="file"
                  accept="application/pdf,.pdf"
                  required
                  aria-describedby="regulation-file-hint"
                  onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
                />
                <p className="field__hint" id="regulation-file-hint">
                  Required. Must be a PDF.{" "}
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => chooseFile(syntheticSampleFile())}
                  >
                    Insert a synthetic sample document
                  </button>
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="Synthetic-data disclosure" icon={FlaskConical}>
            <label className="checkbox" htmlFor="synthetic-ack">
              <input
                id="synthetic-ack"
                type="checkbox"
                checked={ack}
                required
                onChange={(event) => setAck(event.target.checked)}
              />
              <span className="checkbox__text">
                <strong>I confirm this document is synthetic.</strong> It is a demonstration
                document, not a real regulation, and contains no personal data. This confirmation is
                sent as <Mono>synthetic_ack</Mono> and the run is rejected without it.
              </span>
            </label>
          </Panel>

          <Panel title="Confirm and start analysis" icon={ArrowRight}>
            <div className="stack">
              <p className="page__lede">
                Starting the analysis creates a run in the <Mono>INGESTED</Mono> state and begins
                extraction. Actions that would change a document always stop for human approval
                first — nothing consequential happens without a decision from you.
              </p>

              {error ? (
                <Notice tone="critical" title="The run was not created" live>
                  {error.message}
                  {error.details.length > 0 ? (
                    <ul>
                      {error.details.map((detail, index) => (
                        <li key={index}>
                          {detail.location && detail.location.length > 0
                            ? `${detail.location.join(" → ")}: `
                            : ""}
                          {detail.message}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </Notice>
              ) : null}

              {!file || !ack ? (
                <Notice tone="info">
                  {!file && !ack
                    ? "Choose a PDF and confirm the synthetic-data disclosure to continue."
                    : !file
                      ? "Choose a PDF to continue."
                      : "Confirm the synthetic-data disclosure to continue."}
                </Notice>
              ) : null}

              <div className="row">
                <button type="submit" className="btn btn--primary" disabled={!canSubmit}>
                  {submitting ? (
                    <Loader2 size={16} aria-hidden="true" className="spin" />
                  ) : (
                    <ArrowRight size={16} aria-hidden="true" />
                  )}
                  {submitting ? "Starting analysis…" : "Confirm and start analysis"}
                </button>
                <button type="button" className="btn" onClick={() => navigate("/")}>
                  Cancel
                </button>
              </div>
            </div>
          </Panel>
        </div>
      </form>
    </>
  );
}

function AcceptedRun({ run, onStartAnother }: { run: Run; onStartAnother: () => void }) {
  const descriptor = RUN_STATE[run.state];

  return (
    <>
      <PageHeader
        title="Analysis started"
        lede="The regulation was accepted and a run was created. Processing progress is polled from the API every two seconds."
        crumbs={[
          { label: "Operations", to: "/" },
          { label: "Regulation intake", to: "/intake" },
          { label: "Accepted" },
        ]}
        status={<StatusBadge descriptor={descriptor} srPrefix="Run state:" size="lg" />}
      />

      <Notice tone="verified" title="Run accepted" icon={CheckCircle2} live>
        Run <Mono>{run.run_id}</Mono> was created at {formatDateTime(run.created_at)}.
      </Notice>

      <Panel title="Accepted regulation" icon={FileText}>
        <dl className="dl">
          <dt>Run</dt>
          <dd>
            <Mono>{run.run_id}</Mono>
          </dd>

          <dt>Regulation id</dt>
          <dd>
            <Mono>{run.regulation.reg_id}</Mono>
          </dd>

          <dt>Title</dt>
          <dd>{run.regulation.title}</dd>

          <dt>Source file</dt>
          <dd>
            <Mono>{run.regulation.source_filename}</Mono>
          </dd>

          <dt>Jurisdiction</dt>
          <dd>{run.regulation.jurisdiction ?? "Not reported"}</dd>

          <dt>Classification</dt>
          <dd>
            <Tag icon={FlaskConical}>Synthetic</Tag>
          </dd>
        </dl>
      </Panel>

      <Panel
        title="Version and change detection"
        icon={FileDiff}
        description="Reported by the API from the document's content hash."
      >
        <ChangeDetectionDetails detection={run.change_detection} />
      </Panel>

      <div className="row">
        <Link className="btn btn--primary" to={`/runs/${run.run_id}`}>
          <ArrowRight size={16} aria-hidden="true" />
          Open run detail
        </Link>
        <Link className="btn" to="/">
          Operations dashboard
        </Link>
        <button type="button" className="btn" onClick={onStartAnother}>
          Start another intake
        </button>
      </div>
    </>
  );
}
