"use client";

/**
 * The live scorecard.
 *
 * Two halves, kept visually separate because they mean different things. The
 * benchmark half needs ground-truth labels and therefore only exists on the
 * synthetic corpus — presenting it beside the operational numbers without that
 * distinction would let a demo figure pass for a production one.
 */

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import type { Scorecard as ScorecardData } from "@/lib/api";
import { DURATION, EASE_OUT, STAGGER } from "@/lib/tokens";
import { Metric, SectionTitle } from "./Bits";

export default function Scorecard({ data }: { data: ScorecardData | null }) {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data || !root.current) return;
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
  }, [data]);

  if (!data) {
    return (
      <div style={{ color: "var(--text-faint)", padding: "1rem" }} className="rs-mono">
        loading scorecard…
      </div>
    );
  }

  const b = data.detector_benchmark;
  const o = data.review_operations;
  const fp = data.false_positive_cost;

  return (
    <div ref={root}>
      <SectionTitle
        right={
          <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
            scope: {data.scope}
          </span>
        }
      >
        Detector benchmark
      </SectionTitle>

      <div style={grid}>
        <div className="rs-metric">
          <Metric
            label="recall"
            value={`${Math.round(b.recall * 100)}%`}
            sub={`${b.rings_detected}/${b.rings_total} seeded rings found`}
            tone="accent"
          />
        </div>
        <div className="rs-metric">
          <Metric
            label="precision"
            value={`${Math.round(b.precision * 100)}%`}
            sub={`${b.false_flags} false flag${b.false_flags === 1 ? "" : "s"}`}
            tone="accent"
          />
        </div>
        <div className="rs-metric">
          <Metric
            label="clean accounts swept in"
            value={`${b.normal_accounts_swept_in}`}
            sub={`of ${b.normal_accounts_total} unlabelled accounts`}
          />
        </div>
      </div>

      <p style={caveat}>
        Requires ground-truth labels, so this half only exists on the synthetic
        corpus. It would be unavailable on real merchant data.
      </p>

      <div style={{ marginTop: "1.6rem" }}>
        <SectionTitle>Review queue</SectionTitle>
        <div style={grid}>
          <div className="rs-metric">
            <Metric label="pending" value={`${o.pending}`} sub="awaiting a human" tone="warn" />
          </div>
          <div className="rs-metric">
            <Metric label="approved" value={`${o.approved}`} sub="confirmed as rings" />
          </div>
          <div className="rs-metric">
            <Metric label="dismissed" value={`${o.dismissed}`} sub="called false positives" />
          </div>
        </div>
      </div>

      <div style={{ marginTop: "1.6rem" }}>
        <SectionTitle>False-positive cost</SectionTitle>
        <div style={grid}>
          <div className="rs-metric">
            <Metric
              label="analyst time on dismissals"
              value={`${fp.analyst_minutes_on_dismissed}m`}
              sub={`at ~${fp.minutes_per_review_assumed}m per review`}
            />
          </div>
          <div className="rs-metric">
            <Metric
              label="dismissed but real"
              value={`${fp.dismissed_that_were_real_rings}`}
              sub="missed rings — the expensive error"
              tone={fp.dismissed_that_were_real_rings > 0 ? "warn" : "default"}
            />
          </div>
          <div className="rs-metric">
            <Metric
              label="needs more data"
              value={`${data.needs_more_data.count}`}
              sub="exceptions, not failures"
            />
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
  lineHeight: 1.5,
};
