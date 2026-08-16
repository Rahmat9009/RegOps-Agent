// EvidenceDetailPage — View 5: evidence detail with the full clickable chain.
//
// regulation citation -> extracted obligation -> conflicting synthetic clause
// -> affected worker case -> proposed action -> verifier verdict
//
// Every link in the chain is anchored to the source document record lower on the
// page, and every quote is reproduced exactly as the API returned it.

import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowRight,
  FileSearch,
  FlaskConical,
  GitCompare,
  Link2,
  Scale,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { api, type EvidenceReference, type Finding } from "@/lib/api";
import { formatDate, humanizeToken } from "@/lib/format";
import {
  ACTION_AUTONOMY,
  ACTION_STATUS,
  ACTION_TYPE,
  DOCUMENT_KIND,
  FINDING_STATUS,
  OBLIGATION_TYPE,
  RELATIONSHIP,
  SEVERITY,
  SOURCE_AUTHORITY,
  VERDICT,
  humanReviewDescriptor,
} from "@/lib/presentation";
import { useAsync } from "@/hooks/useAsync";
import { Mono, StatusBadge, Tag } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { ScoreMeter } from "@/components/Meter";
import { ErrorState, LoadingState } from "@/components/states";

export function EvidenceDetailPage() {
  const { findingId = "" } = useParams();
  const loader = useCallback(() => api.getFinding(findingId), [findingId]);
  const { data: finding, error, loading, reload } = useAsync(loader);

  if (loading) {
    return (
      <>
        <PageHeader title="Evidence detail" />
        <Panel title="Finding" icon={FileSearch}>
          <LoadingState label="Loading evidence chain…" />
        </Panel>
      </>
    );
  }

  if (error || !finding) {
    return (
      <>
        <PageHeader title="Evidence detail" />
        <Panel title="Finding" icon={FileSearch}>
          {error ? <ErrorState error={error} onRetry={reload} /> : null}
        </Panel>
      </>
    );
  }

  return <EvidenceDetail finding={finding} />;
}

function EvidenceDetail({ finding }: { finding: Finding }) {
  const documents = uniqueDocuments(finding);
  const regulationEvidence = finding.obligation.evidence[0];
  const targetEvidence = finding.evidence_path.find(
    (item) => item.doc_kind === "contract" || item.doc_kind === "policy",
  );
  const caseEvidence = finding.evidence_path.find((item) => item.doc_kind === "case");

  return (
    <>
      <PageHeader
        title={`Finding ${finding.finding_id}`}
        lede={`${RELATIONSHIP[finding.relationship].label} ${finding.target_id}. ${
          RELATIONSHIP[finding.relationship].description
        }`}
        crumbs={[
          { label: "Operations", to: "/" },
          { label: `Run ${finding.run_id}`, to: `/runs/${finding.run_id}` },
          { label: "Findings", to: `/runs/${finding.run_id}/findings` },
          { label: finding.finding_id },
        ]}
        status={
          <>
            <StatusBadge descriptor={SEVERITY[finding.severity]} srPrefix="Severity:" size="lg" />
            <StatusBadge descriptor={FINDING_STATUS[finding.status]} srPrefix="Status:" />
          </>
        }
      />

      <Notice tone="review" title="Synthetic records" icon={FlaskConical}>
        The contract, policy and case documents referenced below are synthetic demonstration
        records. RegOps identifies potential conflicts and supports review; it does not determine
        legal compliance.
      </Notice>

      <Panel
        title="Evidence chain"
        icon={Link2}
        description="Each step links to the source document record further down this page."
      >
        <ol className="evidence-chain">
          <ChainStep
            step="1 · Regulation citation"
            icon={Scale}
            title={`${finding.obligation.obligation_id} — cited source`}
          >
            {regulationEvidence ? (
              <EvidenceQuote evidence={regulationEvidence} />
            ) : (
              <p className="field__hint">No citation was returned for this obligation.</p>
            )}
          </ChainStep>

          <ChainStep
            step="2 · Extracted obligation"
            icon={OBLIGATION_TYPE[finding.obligation.type].icon}
            title={finding.obligation.statement}
          >
            <div className="chip-row">
              <StatusBadge
                descriptor={OBLIGATION_TYPE[finding.obligation.type]}
                srPrefix="Obligation type:"
              />
              {finding.obligation.effective_date ? (
                <Tag>Effective {formatDate(finding.obligation.effective_date)}</Tag>
              ) : null}
            </div>
            {finding.obligation.exceptions && finding.obligation.exceptions.length > 0 ? (
              <div>
                <p className="field__hint">Exceptions recorded with this obligation:</p>
                <ul>
                  {finding.obligation.exceptions.map((exception, index) => (
                    <li key={index}>{exception}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="field__hint">No exceptions were recorded for this obligation.</p>
            )}
          </ChainStep>

          <ChainStep
            step="3 · Conflicting synthetic clause"
            icon={GitCompare}
            title={finding.target_id}
          >
            {targetEvidence ? (
              <EvidenceQuote evidence={targetEvidence} />
            ) : (
              <p className="field__hint">
                No contract or policy quote was returned in the evidence path for this finding.
              </p>
            )}
          </ChainStep>

          <ChainStep
            step="4 · Affected worker case"
            icon={DOCUMENT_KIND.case.icon}
            title={finding.affected_case ? finding.affected_case.case_id : "No case attached"}
          >
            {finding.affected_case ? (
              <>
                <p>{finding.affected_case.summary}</p>
                <div className="chip-row">
                  <Tag icon={FlaskConical}>Synthetic case</Tag>
                  {finding.affected_case.signed_date ? (
                    <Tag>Signed {formatDate(finding.affected_case.signed_date)}</Tag>
                  ) : null}
                </div>
                {caseEvidence ? <EvidenceQuote evidence={caseEvidence} /> : null}
              </>
            ) : (
              <p className="field__hint">
                This finding does not reference a worker case. It affects a document rather than an
                individual deployment file.
              </p>
            )}
          </ChainStep>

          <ChainStep
            step="5 · Proposed action"
            icon={
              finding.proposed_action
                ? ACTION_TYPE[finding.proposed_action.type].icon
                : DOCUMENT_KIND.policy.icon
            }
            title={
              finding.proposed_action
                ? ACTION_TYPE[finding.proposed_action.type].label
                : "No action proposed"
            }
          >
            {finding.proposed_action ? (
              <>
                <p>{ACTION_TYPE[finding.proposed_action.type].description}</p>
                <div className="chip-row">
                  <StatusBadge
                    descriptor={ACTION_STATUS[finding.proposed_action.status]}
                    srPrefix="Action status:"
                  />
                  <StatusBadge
                    descriptor={ACTION_AUTONOMY[finding.proposed_action.autonomy]}
                    srPrefix="Autonomy:"
                  />
                </div>
                <dl className="dl">
                  <dt>Action id</dt>
                  <dd>
                    <Mono>{finding.proposed_action.action_id}</Mono>
                  </dd>
                  <dt>Idempotency key</dt>
                  <dd>
                    <Mono>{finding.proposed_action.idempotency_key}</Mono>
                  </dd>
                </dl>
                {finding.proposed_action.type === "draft_amendment" ? (
                  <Link
                    className="btn btn--sm"
                    to={`/actions/${finding.proposed_action.action_id}/preview`}
                  >
                    <ArrowRight size={14} aria-hidden="true" />
                    Counterfactual shadow-state preview
                  </Link>
                ) : null}
              </>
            ) : (
              <p className="field__hint">
                No action was proposed for this finding. Only the Action Controller proposes
                actions, and only from a schema-valid finding.
              </p>
            )}
          </ChainStep>

          <ChainStep
            step="6 · Verifier verdict"
            icon={ShieldCheck}
            title={VERDICT[finding.verdict].label}
          >
            <p>{VERDICT[finding.verdict].description}</p>
            <div className="chip-row">
              <StatusBadge descriptor={VERDICT[finding.verdict]} srPrefix="Verdict:" />
              <StatusBadge
                descriptor={humanReviewDescriptor(finding.human_review_required)}
                srPrefix="Human review:"
              />
            </div>
          </ChainStep>
        </ol>
      </Panel>

      <div className="grid grid--2">
        <Panel title="Confidence and authority" icon={ShieldCheck}>
          <div className="stack">
            <ScoreMeter
              label="Evidence strength"
              value={finding.scores.evidence_strength}
              description="How well the quoted evidence supports the finding."
              tone={finding.scores.evidence_strength >= 0.75 ? "info" : "review"}
            />
            <ScoreMeter
              label="Interpretation confidence"
              value={finding.scores.interpretation_confidence}
              description="How confident the pipeline is in its reading of the obligation. Low confidence is why human review exists."
              tone={finding.scores.interpretation_confidence >= 0.75 ? "info" : "review"}
            />
            <dl className="dl">
              <dt>Source authority</dt>
              <dd>
                <StatusBadge
                  descriptor={SOURCE_AUTHORITY[finding.scores.source_authority]}
                  srPrefix="Source authority:"
                />
                <p className="field__hint">
                  {SOURCE_AUTHORITY[finding.scores.source_authority].description}
                </p>
              </dd>
              <dt>Operational severity</dt>
              <dd>
                <StatusBadge
                  descriptor={SEVERITY[finding.scores.operational_severity]}
                  srPrefix="Operational severity:"
                />
              </dd>
              <dt>Human review</dt>
              <dd>
                <StatusBadge
                  descriptor={humanReviewDescriptor(finding.scores.human_review_required)}
                  srPrefix="Human review:"
                />
              </dd>
            </dl>
          </div>
        </Panel>

        <Panel
          title="Source documents"
          icon={FileSearch}
          description="Every document quoted in the chain above, with its page and exact quote."
        >
          <div className="stack">
            {documents.map((evidence) => (
              <article
                key={`${evidence.doc_id}-${evidence.page}`}
                id={documentAnchor(evidence)}
                className="stack stack--tight"
              >
                <div className="chip-row">
                  <StatusBadge
                    descriptor={DOCUMENT_KIND[evidence.doc_kind]}
                    srPrefix="Document kind:"
                  />
                  <Tag>
                    <Mono>{evidence.doc_id}</Mono>
                  </Tag>
                  <Tag>Page {evidence.page}</Tag>
                </div>
                <EvidenceQuote evidence={evidence} showLink={false} />
              </article>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}

function ChainStep({
  step,
  icon: Icon,
  title,
  children,
}: {
  step: string;
  icon: LucideIcon;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="evidence-link">
      <span className="evidence-link__marker" aria-hidden="true">
        <Icon size={15} />
      </span>
      <div className="evidence-link__body">
        <span className="evidence-link__step">{step}</span>
        <h3>{title}</h3>
        {children}
      </div>
    </li>
  );
}

function EvidenceQuote({
  evidence,
  showLink = true,
}: {
  evidence: EvidenceReference;
  showLink?: boolean;
}) {
  return (
    <figure className="quote">
      <blockquote cite={evidence.doc_id}>{evidence.quote}</blockquote>
      <footer>
        {humanizeToken(evidence.doc_kind)} <Mono>{evidence.doc_id}</Mono>, page {evidence.page}
        {showLink ? (
          <>
            {" · "}
            <a href={`#${documentAnchor(evidence)}`}>Jump to source document</a>
          </>
        ) : null}
      </footer>
    </figure>
  );
}

function documentAnchor(evidence: EvidenceReference): string {
  return `doc-${evidence.doc_id}-p${evidence.page}`.replace(/[^a-zA-Z0-9-]/g, "-");
}

/** Deduplicate the chain's references by document id + page. */
function uniqueDocuments(finding: Finding): EvidenceReference[] {
  const all = [...finding.obligation.evidence, ...finding.evidence_path];
  const seen = new Set<string>();
  const result: EvidenceReference[] = [];
  for (const evidence of all) {
    const key = `${evidence.doc_id}:${evidence.page}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(evidence);
  }
  return result;
}
