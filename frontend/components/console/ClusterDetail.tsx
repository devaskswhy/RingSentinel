"use client";

/**
 * The review pane: case file, evidence, graph, audit trail, and the decision.
 *
 * The decision controls deliberately refuse to submit without a reason. That is
 * not politeness — the backend rejects a short reason with a 422, and the audit
 * log is the only record of why a human decided what they decided. Failing in
 * the form is better than failing after a round trip.
 */

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { api, type ClusterDetail as Detail } from "@/lib/api";
import { DURATION, EASE_OUT } from "@/lib/tokens";
import AuditTrail from "./AuditTrail";
import GraphView from "./GraphView";
import { ActionPill, CadencePill, ScoreBar, SectionTitle, StatusPill } from "./Bits";

type Pending = "approve" | "dismiss" | null;

export default function ClusterDetail({
  detail,
  onReviewed,
  onGenerated,
}: {
  detail: Detail;
  onReviewed: () => void;
  onGenerated: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [intent, setIntent] = useState<Pending>(null);
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState("analyst");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const { cluster, case_file, evidence, graph, audit_trail } = detail;
  const decided = cluster.status !== "pending";

  useEffect(() => {
    if (!root.current) return;
    const ctx = gsap.context(() => {
      gsap.from(".rs-detail-block", {
        opacity: 0,
        y: 12,
        duration: DURATION.fast,
        ease: EASE_OUT,
        stagger: 0.05,
      });
    }, root);
    return () => ctx.revert();
  }, [cluster.id]);

  // Reset the form when a different cluster is opened, so a half-typed reason
  // can never be submitted against the wrong one.
  useEffect(() => {
    setIntent(null);
    setReason("");
    setError(null);
  }, [cluster.id]);

  async function submit() {
    if (!intent) return;
    setBusy(true);
    setError(null);
    try {
      const fn = intent === "approve" ? api.approve : api.dismiss;
      await fn(cluster.id, reason.trim(), reviewer.trim() || "analyst");
      setIntent(null);
      setReason("");
      onReviewed();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      await api.generateCaseFile(cluster.id);
      onGenerated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  }

  const reasonTooShort = reason.trim().length < 5;

  return (
    <div ref={root} style={{ display: "flex", flexDirection: "column", gap: "1.75rem" }}>
      {/* ---- header ---------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
          <StatusPill status={cluster.status} />
          <CadencePill cadence={cluster.cadence} />
          {case_file && <ActionPill action={case_file.suggested_action} />}
          <span className="rs-mono" style={{ color: "var(--text-faint)", marginLeft: "auto" }}>
            {cluster.id.slice(0, 8)} · detector {cluster.detector_version}
          </span>
        </div>
        <h2 style={{ fontSize: "var(--step-2)", marginTop: "0.9rem", maxWidth: "48ch" }}>
          {evidence.headline}
        </h2>
        <div style={{ marginTop: "0.75rem" }}>
          <ScoreBar score={cluster.score} />
        </div>
      </div>

      {/* ---- case file ------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle
          right={
            case_file ? (
              <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
                {case_file.model}
                {case_file.stale && " · stale"}
              </span>
            ) : undefined
          }
        >
          Case file
        </SectionTitle>

        {case_file ? (
          <div style={panel}>
            <p style={{ margin: 0, lineHeight: 1.65 }}>{case_file.summary}</p>

            <div style={{ marginTop: "1.1rem" }}>
              <div className="rs-label" style={{ marginBottom: "0.4rem" }}>
                Confidence
              </div>
              <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "var(--step--1)" }}>
                {case_file.confidence_note}
              </p>
            </div>

            {case_file.key_signals.length > 0 && (
              <div style={{ marginTop: "1.1rem" }}>
                <div className="rs-label" style={{ marginBottom: "0.4rem" }}>
                  Key signals
                </div>
                <ul style={listStyle}>
                  {case_file.key_signals.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}

            {case_file.caveats.length > 0 && (
              <div style={{ marginTop: "1.1rem" }}>
                <div className="rs-label" style={{ marginBottom: "0.4rem" }}>
                  What would change this
                </div>
                <ul style={{ ...listStyle, color: "var(--text-faint)" }}>
                  {case_file.caveats.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}

            <p
              style={{
                marginTop: "1.2rem",
                paddingTop: "0.8rem",
                borderTop: "1px solid var(--line)",
                color: "var(--text-faint)",
                fontSize: "0.72rem",
              }}
            >
              {case_file.disclaimer}
            </p>
          </div>
        ) : (
          <div style={{ ...panel, textAlign: "center" }}>
            <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
              No case file yet for this cluster.
            </p>
            <button onClick={generate} disabled={generating} style={buttonPrimary}>
              {generating ? "Claude is writing…" : "Generate case file"}
            </button>
          </div>
        )}
      </div>

      {/* ---- evidence -------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle>Why it scored {cluster.score.toFixed(3)}</SectionTitle>
        <div style={{ ...panel, display: "grid", gap: "0.7rem" }}>
          {Object.entries(evidence.signals).map(([name, s]) => (
            <div key={name}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "var(--step--1)",
                  marginBottom: "0.25rem",
                }}
              >
                <span>{name.replace(/_/g, " ")}</span>
                <span className="rs-mono" style={{ color: "var(--text-muted)" }}>
                  {s.value.toFixed(2)} × {s.weight} = {s.weighted.toFixed(3)}
                </span>
              </div>
              <div style={{ height: 3, background: "var(--line-strong)", overflow: "hidden" }}>
                <div
                  className="rs-anim"
                  style={{
                    height: "100%",
                    background: "var(--accent)",
                    transform: `scaleX(${Math.max(0, Math.min(1, s.value))})`,
                    transformOrigin: "left center",
                  }}
                />
              </div>
              <div style={{ color: "var(--text-faint)", fontSize: "0.7rem", marginTop: "0.25rem" }}>
                {s.explanation}
              </div>
            </div>
          ))}

          <div style={{ borderTop: "1px solid var(--line)", paddingTop: "0.7rem" }}>
            <div className="rs-label" style={{ marginBottom: "0.45rem" }}>
              Shared attributes
            </div>
            {evidence.shared_attributes.map((a) => (
              <div
                key={a.entity_id}
                className="rs-mono"
                style={{ color: "var(--text-muted)", marginBottom: "0.2rem" }}
              >
                {a.customer_count} accounts · {a.attribute_type} ·{" "}
                {a.observations} transactions
              </div>
            ))}
          </div>

          <div style={{ borderTop: "1px solid var(--line)", paddingTop: "0.7rem" }}>
            <div className="rs-label" style={{ marginBottom: "0.45rem" }}>
              Timing
            </div>
            <div className="rs-mono" style={{ color: "var(--text-muted)" }}>
              cluster median gap {evidence.timing.cluster_median_gap_seconds}s vs
              platform baseline {Math.round(evidence.timing.baseline_median_gap_seconds)}s
            </div>
            <div style={{ color: "var(--text-faint)", fontSize: "0.72rem", marginTop: "0.35rem" }}>
              {evidence.cadence.reason}
            </div>
          </div>
        </div>
      </div>

      {/* ---- graph ----------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle
          right={
            <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
              {graph.nodes.length} nodes · {graph.edges.length} edges
            </span>
          }
        >
          Entity graph
        </SectionTitle>
        <div style={panel}>
          <GraphView nodes={graph.nodes} edges={graph.edges} />
        </div>
      </div>

      {/* ---- decision -------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle>Decision</SectionTitle>
        <div style={panel}>
          {decided ? (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              Already reviewed — recorded as <StatusPill status={cluster.status} />. A
              decision is made once; the audit log is not rewritten.
            </p>
          ) : (
            <>
              <p
                style={{
                  marginTop: 0,
                  color: "var(--text-faint)",
                  fontSize: "0.75rem",
                }}
              >
                Neither action blocks, freezes, or restricts any account.
                RingSentinel records your judgement and nothing else.
              </p>

              <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                <button
                  onClick={() => setIntent(intent === "approve" ? null : "approve")}
                  style={intent === "approve" ? buttonPrimary : buttonGhost}
                >
                  Approve — this is a ring
                </button>
                <button
                  onClick={() => setIntent(intent === "dismiss" ? null : "dismiss")}
                  style={intent === "dismiss" ? buttonWarn : buttonGhost}
                >
                  Dismiss — false positive
                </button>
              </div>

              {intent && (
                <div style={{ marginTop: "1rem", display: "grid", gap: "0.6rem" }}>
                  <label className="rs-label" htmlFor="rs-reason">
                    Reason (required, recorded permanently)
                  </label>
                  <textarea
                    id="rs-reason"
                    className="rs-focus"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    rows={3}
                    placeholder={
                      intent === "approve"
                        ? "What convinced you this is coordinated?"
                        : "What innocent explanation fits the evidence?"
                    }
                    style={inputStyle}
                  />
                  <input
                    className="rs-focus"
                    value={reviewer}
                    onChange={(e) => setReviewer(e.target.value)}
                    placeholder="your name"
                    style={{ ...inputStyle, maxWidth: 240 }}
                  />
                  <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
                    <button
                      onClick={submit}
                      disabled={busy || reasonTooShort}
                      style={{
                        ...(intent === "approve" ? buttonPrimary : buttonWarn),
                        opacity: busy || reasonTooShort ? 0.45 : 1,
                        cursor: busy || reasonTooShort ? "not-allowed" : "pointer",
                      }}
                    >
                      {busy ? "Recording…" : `Confirm ${intent}`}
                    </button>
                    {reasonTooShort && (
                      <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
                        a reason of at least 5 characters is required
                      </span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {error && (
            <p style={{ color: "#fca5a5", fontSize: "var(--step--1)", marginBottom: 0 }}>
              {error}
            </p>
          )}
        </div>
      </div>

      {/* ---- audit ----------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle>Audit trail · append-only</SectionTitle>
        <AuditTrail entries={audit_trail} />
      </div>
    </div>
  );
}

const panel: React.CSSProperties = {
  background: "var(--ink-panel)",
  border: "1px solid var(--line)",
  padding: "1.1rem 1.2rem",
};

const listStyle: React.CSSProperties = {
  margin: 0,
  paddingLeft: "1.1rem",
  color: "var(--text-muted)",
  fontSize: "var(--step--1)",
  lineHeight: 1.7,
};

const inputStyle: React.CSSProperties = {
  background: "var(--ink)",
  border: "1px solid var(--line-strong)",
  color: "var(--text)",
  padding: "0.6rem 0.7rem",
  fontFamily: "var(--font-body)",
  fontSize: "var(--step--1)",
  resize: "vertical",
};

const buttonBase: React.CSSProperties = {
  padding: "0.55rem 1rem",
  fontSize: "var(--step--1)",
  fontWeight: 600,
  border: "1px solid transparent",
  cursor: "pointer",
  transition: "transform var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease)",
};

const buttonPrimary: React.CSSProperties = {
  ...buttonBase,
  background: "var(--accent)",
  color: "var(--ink)",
};

const buttonWarn: React.CSSProperties = {
  ...buttonBase,
  background: "#fcd34d",
  color: "var(--ink)",
};

const buttonGhost: React.CSSProperties = {
  ...buttonBase,
  background: "transparent",
  borderColor: "var(--line-strong)",
  color: "var(--text)",
};
