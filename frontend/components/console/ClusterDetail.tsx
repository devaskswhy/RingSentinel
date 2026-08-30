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
import { api, type ClusterDetail as Detail, type EvidencePack } from "@/lib/api";
import { DURATION, EASE_OUT, prefersReducedMotion } from "@/lib/tokens";
import { speak, speechSupported, stopSpeaking } from "@/lib/speech";
import AuditTrail from "./AuditTrail";
import GraphView from "./GraphView";
import { ActionTag, CadenceTag, ScoreBar, SectionTitle, StatusTag } from "./Bits";

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

  // The pack re-verifies the whole audit chain, so it is fetched only when a
  // reviewer asks for it rather than on every cluster open.
  const [pack, setPack] = useState<EvidencePack | null>(null);
  const [packBusy, setPackBusy] = useState(false);
  const [packError, setPackError] = useState<string | null>(null);

  // Reading the case file aloud speaks CLAUDE'S OWN WORDS — the summary, the
  // confidence note and the key signals it wrote, in that order. Not a
  // paraphrase and not a second model pass: the point of a spoken case file is
  // that it is the same artefact the audit log records, just heard instead of
  // read.
  const [reading, setReading] = useState(false);
  const speakable = typeof window !== "undefined" && speechSupported();
  const cancelRead = useRef<(() => void) | null>(null);

  const { cluster, case_file, evidence, graph, audit_trail, counterfactual } = detail;
  const decided = cluster.status !== "pending";

  useEffect(() => {
    if (!root.current) return;
    if (prefersReducedMotion()) return;
    const ctx = gsap.context(() => {
      // The case cascades in rather than appearing whole. Opening a cluster is
      // the one moment in this console where a reviewer's attention has to move
      // from the queue to a document, and staggering the seven sections walks
      // the eye down them in the order they are meant to be read.
      gsap.from(".rs-detail-block", {
        opacity: 0,
        y: 26,
        duration: DURATION.slow * 0.55,
        ease: EASE_OUT,
        stagger: 0.07,
      });
    }, root);
    return () => ctx.revert();
  }, [cluster.id]);

  // Reset the form when a different cluster is opened, so a half-typed reason
  // can never be submitted against the wrong one.
  // Stop any narration when the cluster changes or the pane unmounts. A voice
  // still describing the previous cluster would be worse than no voice at all.
  useEffect(() => () => stopSpeaking(), []);

  useEffect(() => {
    cancelRead.current?.();
    setReading(false);
    setIntent(null);
    setReason("");
    setError(null);
    // The pack is per-cluster too. Showing a previous cluster's verification
    // under a new cluster's heading would be a lie about which rows were checked.
    setPack(null);
    setPackError(null);
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

  function toggleRead() {
    if (reading) {
      cancelRead.current?.();
      return;
    }
    if (!case_file) return;
    const script = [
      case_file.summary,
      case_file.confidence_note,
      ...(case_file.key_signals ?? []),
    ]
      .filter(Boolean)
      .join(" ");
    setReading(true);
    cancelRead.current = speak(script, () => {
      setReading(false);
      cancelRead.current = null;
    });
  }

  const reasonTooShort = reason.trim().length < 5;

  return (
    <div ref={root} style={{ display: "flex", flexDirection: "column", gap: "1.75rem" }}>
      {/* ---- header ---------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
          <StatusTag status={cluster.status} />
          <CadenceTag cadence={cluster.cadence} />
          {case_file && <ActionTag action={case_file.suggested_action} />}
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
          step={1}
          right={
            case_file ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.75rem" }}>
                <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
                  {case_file.model}
                  {case_file.stale && " · stale"}
                </span>
                {speakable && (
                  <button
                    onClick={toggleRead}
                    className="rs-focus rs-guide-replay"
                    title="Read Claude's case file aloud. These are its words, not a summary of them."
                  >
                    {reading ? "◼ stop" : "▶ read aloud"}
                  </button>
                )}
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
              <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "var(--console-body)" }}>
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
                fontSize: "var(--console-small)",
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
        <SectionTitle step={2}>Why it scored {cluster.score.toFixed(3)}</SectionTitle>
        <div style={{ ...panel, display: "grid", gap: "0.7rem" }}>
          {Object.entries(evidence.signals).map(([name, s]) => (
            <div key={name}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "var(--console-body)",
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
              <div style={{ color: "var(--text-faint)", fontSize: "var(--console-label)", marginTop: "0.25rem" }}>
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
            <div style={{ color: "var(--text-faint)", fontSize: "var(--console-small)", marginTop: "0.35rem" }}>
              {evidence.cadence.reason}
            </div>
          </div>
        </div>
      </div>

      {/* ---- counterfactual -------------------------------------------
          The question a reviewer actually asks after reading a score: how
          close was this? Answerable only because the score is a sum of named
          signals rather than a model output. */}
      {counterfactual && (
        <div className="rs-detail-block rs-anim">
          <SectionTitle
            step={3}
            right={
              <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
                {counterfactual.gap >= 0 ? "+" : ""}
                {counterfactual.gap.toFixed(3)} from {counterfactual.boundary_name}
              </span>
            }
          >
            How close was this?
          </SectionTitle>
          <div style={panel}>
            <p style={{ margin: 0, fontSize: "var(--step-0)", lineHeight: 1.55 }}>
              {counterfactual.reading}
            </p>

            {counterfactual.smallest_change && (
              <div
                className="rs-mono"
                style={{
                  marginTop: "0.85rem",
                  paddingTop: "0.85rem",
                  borderTop: "1px solid var(--line)",
                  color: "var(--text-muted)",
                  display: "grid",
                  gap: "0.3rem",
                }}
              >
                <div>
                  change tested ·{" "}
                  <span style={{ color: "var(--text)" }}>
                    {counterfactual.smallest_change.change}
                  </span>
                </div>
                <div style={{ fontVariantNumeric: "tabular-nums" }}>
                  {counterfactual.current_score.toFixed(3)} →{" "}
                  <span
                    style={{
                      color: counterfactual.smallest_change.would_cross
                        ? "var(--signal)"
                        : "var(--text)",
                    }}
                  >
                    {counterfactual.smallest_change.score_would_become.toFixed(3)}
                  </span>{" "}
                  ({counterfactual.smallest_change.delta >= 0 ? "+" : ""}
                  {counterfactual.smallest_change.delta.toFixed(4)}) ·{" "}
                  {counterfactual.smallest_change.would_cross
                    ? "crosses the boundary"
                    : "does not cross"}
                </div>
              </div>
            )}

            <p
              style={{
                marginTop: "0.85rem",
                marginBottom: 0,
                color: "var(--text-faint)",
                fontSize: "var(--console-body)",
              }}
            >
              {counterfactual.note}
            </p>
          </div>
        </div>
      )}

      {/* ---- graph ----------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle
          step={4}
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

          {/* The graph alone showed shapes and a tooltip. What a reviewer needs
              is the sentence the shapes are making: how many accounts, what
              they converge on, and how much traffic ran through each one. */}
          <div className="rs-graph-key">
            <p className="rs-graph-read">
              <b>{evidence.size} accounts</b> — the blue circles — converge on{" "}
              <b>
                {(evidence.shared_attributes ?? []).length} shared{" "}
                {(evidence.shared_attributes ?? []).length === 1
                  ? "attribute"
                  : "attributes"}
              </b>
              , the grey diamonds. Any one account using a card is unremarkable.
              This many arriving at the same one is the signal.
            </p>

            <ul className="rs-graph-attrs">
              {(evidence.shared_attributes ?? []).map((a) => (
                <li key={a.entity_id}>
                  <span className="rs-graph-attr-type">{a.attribute_type}</span>
                  <code className="rs-mono">{a.external_ref}</code>
                  <span className="rs-graph-attr-n">
                    {a.customer_count} accounts · {a.observations} transactions
                  </span>
                </li>
              ))}
            </ul>

            <p className="rs-graph-note">
              A grey diamond is a device, card, or address more than one account
              used. Edge thickness is how many transactions ran through that
              link. Attribute references are salted tokens — never a real card
              number or address.
            </p>
          </div>
        </div>
      </div>

      {/* ---- decision -------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle step={5}>Decision</SectionTitle>
        <div style={panel}>
          {decided ? (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              Already reviewed — recorded as <StatusTag status={cluster.status} />. A
              decision is made once; the audit log is not rewritten.
            </p>
          ) : (
            <>
              <p
                style={{
                  marginTop: 0,
                  color: "var(--text-faint)",
                  fontSize: "var(--console-label)",
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
            <p style={{ color: "var(--danger)", fontSize: "var(--console-body)", marginBottom: 0 }}>
              {error}
            </p>
          )}
        </div>
      </div>

      {/* ---- audit ----------------------------------------------------- */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle step={6}>Audit trail · append-only</SectionTitle>
        <AuditTrail entries={audit_trail} />
      </div>

      {/* ---- evidence pack ---------------------------------------------
          The append-only trigger BLOCKS tampering; the hash chain makes it
          DETECTABLE, which is the stronger claim — someone with raw database
          access can drop a trigger, but they cannot make the arithmetic add up
          afterwards. This button is the only place that is visible from the
          product rather than from curl. */}
      <div className="rs-detail-block rs-anim">
        <SectionTitle
          step={7}
          right={
            pack && (
              <span
                className="rs-tag"
                data-tone={pack.integrity.chain_intact ? "accent" : "signal"}
                style={{
                  color: pack.integrity.chain_intact ? "var(--accent)" : "var(--danger)",
                }}
              >
                {pack.integrity.chain_intact ? "CHAIN INTACT" : "CHAIN BROKEN"}
              </span>
            )
          }
        >
          Evidence pack
        </SectionTitle>

        <div style={panel}>
          {!pack && (
            <>
              <p
                style={{
                  margin: "0 0 0.9rem",
                  color: "var(--text-muted)",
                  fontSize: "var(--console-body)",
                }}
              >
                One self-contained bundle: the evidence, Claude&apos;s explanation
                and what it cost, the human decision and its written reason, and a
                re-verification of the hash chain the audit rows sit in.
              </p>
              <button
                onClick={async () => {
                  setPackBusy(true);
                  setPackError(null);
                  try {
                    setPack(await api.evidencePack(cluster.id));
                  } catch (e) {
                    setPackError(e instanceof Error ? e.message : String(e));
                  } finally {
                    setPackBusy(false);
                  }
                }}
                disabled={packBusy}
                className="rs-focus"
                style={{ ...buttonGhost, cursor: packBusy ? "wait" : "pointer" }}
              >
                {packBusy ? "verifying chain…" : "Build and verify →"}
              </button>
              {packError && (
                <p
                  style={{
                    color: "var(--danger)",
                    fontSize: "var(--console-body)",
                    marginBottom: 0,
                  }}
                >
                  {packError}
                </p>
              )}
            </>
          )}

          {pack && (
            <div style={{ display: "grid", gap: "0.85rem" }}>
              <p
                style={{
                  margin: 0,
                  fontSize: "var(--step-0)",
                  color: pack.integrity.chain_intact ? "var(--text)" : "var(--danger)",
                }}
              >
                {pack.integrity.summary}
              </p>

              <div
                className="rs-mono"
                style={{
                  display: "grid",
                  gap: "0.3rem",
                  paddingTop: "0.85rem",
                  borderTop: "1px solid var(--line)",
                  color: "var(--text-muted)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                <Row k="rows verified" v={pack.integrity.rows_verified.toLocaleString()} />
                {pack.explanation && (
                  <>
                    <Row k="explained by" v={pack.explanation.model} />
                    <Row k="cost" v={`$${pack.explanation.cost_usd.toFixed(4)}`} />
                  </>
                )}
                <Row k="decision" v={pack.decision.action ?? "not yet decided"} />
                <Row
                  k="digest"
                  v={`${pack.bundle_digest.algorithm}:${pack.bundle_digest.value.slice(0, 16)}…`}
                />
              </div>

              {/* Precision matters here: a checksum is not a signature. */}
              <p
                style={{
                  margin: 0,
                  color: "var(--text-faint)",
                  fontSize: "var(--console-body)",
                }}
              >
                {pack.bundle_digest.note}
              </p>

              <details>
                <summary
                  className="rs-label rs-focus"
                  style={{ cursor: "pointer", listStyle: "none" }}
                >
                  What this guarantees ({pack.guarantees.length}) ▾
                </summary>
                <ul
                  style={{
                    margin: "0.7rem 0 0",
                    paddingLeft: "1.1rem",
                    color: "var(--text-muted)",
                    fontSize: "var(--console-body)",
                    display: "grid",
                    gap: "0.45rem",
                  }}
                >
                  {pack.guarantees.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </details>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** One key/value line in a mono readout. */
function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
      <span style={{ color: "var(--text-faint)" }}>{k}</span>
      <span style={{ color: "var(--text)", textAlign: "right" }}>{v}</span>
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
  fontSize: "var(--console-body)",
  lineHeight: 1.7,
};

const inputStyle: React.CSSProperties = {
  background: "var(--ink)",
  border: "1px solid var(--line-strong)",
  color: "var(--text)",
  padding: "0.6rem 0.7rem",
  fontFamily: "var(--font-body)",
  fontSize: "var(--console-body)",
  resize: "vertical",
};

const buttonBase: React.CSSProperties = {
  padding: "0.55rem 1rem",
  fontSize: "var(--console-body)",
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
  background: "var(--signal)",
  color: "var(--ink)",
};

const buttonGhost: React.CSSProperties = {
  ...buttonBase,
  background: "transparent",
  borderColor: "var(--line-strong)",
  color: "var(--text)",
};
