"use client";

/**
 * The live scorecard.
 *
 * Three tiers, kept visually separate because they mean different things and
 * merging them would let the strongest number borrow credibility for the
 * weakest:
 *
 *   Held-out benchmark  precision, recall, false-positive cost, measured once
 *                       against rings the detector never saw during tuning.
 *                       Needs ground truth, so it exists only on the synthetic
 *                       corpus.
 *   Exceptions          clusters the detector declined to be confident about.
 *                       Reported as a count, not hidden inside recall.
 *   Review queue        works without labels; identical on real merchant data.
 */

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { api, type HeldOutMetrics, type Scorecard as ScorecardData } from "@/lib/api";
import { DURATION, EASE_OUT, STAGGER } from "@/lib/tokens";
import { Metric, SectionTitle } from "./Bits";

export default function Scorecard({ data }: { data: ScorecardData | null }) {
  const root = useRef<HTMLDivElement>(null);
  const [held, setHeld] = useState<HeldOutMetrics | null>(null);
  const [showAssumptions, setShowAssumptions] = useState(false);
  // The console polls every few seconds. Animating the metric tiles on every
  // refresh would make the whole panel flicker; animate once, on first data.
  const hasAnimated = useRef(false);

  useEffect(() => {
    api.metrics("holdout").then(setHeld).catch(() => setHeld(null));
  }, []);

  useEffect(() => {
    if (!data || !root.current || hasAnimated.current) return;
    hasAnimated.current = true;
    const ctx = gsap.context(() => {
      gsap.from(".rs-metric", {
        opacity: 0,
        y: 10,
        duration: DURATION.fast,
        ease: EASE_OUT,
        stagger: STAGGER,
      });
    }, root);
    return () => ctx.revert();
  }, [data, held]);

  if (!data) {
    return (
      <div style={{ color: "var(--text-faint)", padding: "1rem" }} className="rs-mono">
        loading scorecard…
      </div>
    );
  }

  const o = data.review_operations;

  return (
    <div ref={root}>
      {/* ---- held-out benchmark ------------------------------------- */}
      <SectionTitle
        right={
          held ? (
            <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
              rings {held.confusion.rings_detected}/{held.confusion.rings_total} ·
              detector {held.detector_version}
            </span>
          ) : undefined
        }
      >
        Held-out benchmark — rings never used for tuning
      </SectionTitle>

      {held ? (
        <>
          <div style={grid}>
            <div className="rs-metric">
              <Metric
                label="precision"
                value={`${Math.round(held.headline.precision * 100)}%`}
                sub={`${held.confusion.true_positives_clusters} of ${
                  held.confusion.true_positives_clusters +
                  held.confusion.false_positives_clusters
                } flagged clusters were real`}
                tone="accent"
              />
            </div>
            <div className="rs-metric">
              <Metric
                label="recall"
                value={`${Math.round(held.headline.recall * 100)}%`}
                sub={`${held.confusion.rings_detected} of ${held.confusion.rings_total} seeded rings found`}
                tone="accent"
              />
            </div>
            <div className="rs-metric">
              <Metric
                label="false-positive cost"
                value={`₹${held.cost.total_inr.toLocaleString("en-IN")}`}
                sub={`${held.confusion.false_positives_clusters} FP × ₹${held.cost.review_cost_per_fp_inr} review time`}
                tone={held.confusion.false_positives_clusters > 0 ? "warn" : "default"}
              />
            </div>
          </div>

          <p style={caveat}>
            Precision counts <strong>clusters</strong> (analyst time is spent per
            cluster); recall counts <strong>rings</strong>. Different units on
            purpose — one blended F1 would be tidier and mean less.{" "}
            <button
              onClick={() => setShowAssumptions((v) => !v)}
              style={linkButton}
              className="rs-focus"
            >
              {showAssumptions ? "hide" : "show"} cost assumptions
            </button>
          </p>

          {showAssumptions && (
            <div style={assumptionBox}>
              <div className="rs-label" style={{ marginBottom: "0.5rem" }}>
                Estimates, not measurements
              </div>
              {Object.entries(held.cost_model.assumptions)
                .filter(([k]) => k !== "disclaimer")
                .map(([k, v]) => (
                  <div key={k} className="rs-mono" style={{ color: "var(--text-muted)" }}>
                    {k.replace(/_/g, " ")}: {String(v)}
                  </div>
                ))}
              <p style={{ ...caveat, marginTop: "0.6rem" }}>{held.cost.note}</p>
            </div>
          )}

          {/* ---- exceptions ----------------------------------------- */}
          <div style={{ marginTop: "1.6rem" }}>
            <SectionTitle
              right={
                <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
                  band [{held.needs_review.band[0]}, {held.needs_review.band[1]})
                </span>
              }
            >
              Exceptions — detector declined to be confident
            </SectionTitle>
            <div style={assumptionBox}>
              <div
                style={{
                  fontFamily: "var(--font-display)",
                  fontSize: "var(--step-2)",
                  color: held.needs_review.count > 0 ? "var(--signal)" : "var(--text)",
                }}
              >
                {held.needs_review.count}
              </div>
              <p style={{ ...caveat, marginTop: "0.4rem" }}>{held.needs_review.note}</p>
              {held.needs_review.clusters.map((c, i) => (
                <div
                  key={i}
                  className="rs-mono"
                  style={{ color: "var(--text-muted)", marginTop: "0.45rem" }}
                >
                  {c.score.toFixed(3)} · {c.size} accounts · {c.cadence} —{" "}
                  {c.headline.slice(0, 60)}
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="rs-mono" style={{ color: "var(--text-faint)", padding: "0.5rem 0" }}>
          held-out metrics unavailable — run{" "}
          <code>scripts.report --store</code>
        </div>
      )}

      {/* ---- live queue -------------------------------------------- */}
      <div style={{ marginTop: "1.6rem" }}>
        <SectionTitle>Review queue — works without labels</SectionTitle>
        <div style={grid}>
          <div className="rs-metric">
            <Metric label="pending" value={`${o.pending}`} sub="awaiting a human" tone="warn" />
          </div>
          <div className="rs-metric">
            <Metric
              label="needs review"
              value={`${o.needs_review}`}
              sub="flagged, low confidence"
            />
          </div>
          <div className="rs-metric">
            <Metric label="approved" value={`${o.approved}`} sub="confirmed as rings" />
          </div>
          <div className="rs-metric">
            <Metric label="dismissed" value={`${o.dismissed}`} sub="called false positives" />
          </div>
        </div>
      </div>

      {data.claude_agreement.rate !== null && (
        <p style={caveat}>
          Human agreed with Claude on {data.claude_agreement.agreed} of{" "}
          {data.claude_agreement.decided} decided clusters. Claude never decides —
          this only measures whether its advice was useful.
        </p>
      )}
    </div>
  );
}

const grid: React.CSSProperties = {
  display: "grid",
  gap: 1,
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  background: "var(--line)",
  border: "1px solid var(--line)",
};

const caveat: React.CSSProperties = {
  marginTop: "0.7rem",
  color: "var(--text-faint)",
  fontSize: "0.72rem",
  lineHeight: 1.55,
};

const assumptionBox: React.CSSProperties = {
  marginTop: "0.6rem",
  padding: "0.8rem 0.9rem",
  background: "var(--ink-panel)",
  border: "1px solid var(--line)",
};

const linkButton: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--accent)",
  cursor: "pointer",
  padding: 0,
  font: "inherit",
  textDecoration: "underline",
};
