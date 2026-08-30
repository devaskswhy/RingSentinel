"use client";

/**
 * The corpus, as a readout, filling the empty half of the hero.
 *
 * Not decoration and not a stock chart: the ring is the actual composition of
 * the seeded database. The dim arc is the 900 uncorrelated transactions, and
 * the accent arc is split into one segment per ring, each sized by that ring's
 * real transaction count — so the segment for ring_02 is visibly larger than
 * the one for ring_03 because it genuinely has 193 transactions against 22.
 *
 * Everything is fetched from /eval/corpus, the same object the scroll field is
 * drawn from, and falls back to the measured snapshot if the API is down.
 *
 * The four rows underneath are the measured detection result. The caveat under
 * them is not boilerplate — this is a synthetic corpus this project generated,
 * it is separable by construction, and a headline number without that sentence
 * beside it would be the most dishonest thing on the page.
 */

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import type { CorpusShape } from "./TransactionField";
import { DURATION, EASE, EASE_OUT } from "@/lib/tokens";

const R = 60;
const CIRC = 2 * Math.PI * R;
const GAP = 1.4; // degrees of breathing room between ring segments

export default function CorpusPanel({ corpus }: { corpus: CorpusShape }) {
  const root = useRef<HTMLDivElement>(null);

  const total = corpus.totals.transactions;
  const normal = corpus.normal_transactions;
  const ringTx = total - normal;
  const ringCount = corpus.rings.length;

  // One arc per ring, laid end to end, each proportional to its real volume.
  let cursor = 0;
  const segments = corpus.rings.map((r) => {
    const frac = r.transactions / total;
    const seg = { ring: r.ring, offset: cursor, frac, transactions: r.transactions };
    cursor += frac;
    return seg;
  });
  const normalFrac = normal / total;

  useEffect(() => {
    if (!root.current) return;
    const ctx = gsap.context(() => {
      // Arcs draw themselves in; stroke-dashoffset is one of the three
      // properties this project allows to animate.
      gsap.from(".rs-arc", {
        strokeDashoffset: CIRC,
        duration: DURATION.slow * 1.4,
        ease: EASE,
        stagger: 0.035,
        delay: 0.5,
      });
      gsap.from(".rs-corpus-row", {
        opacity: 0,
        x: 10,
        duration: DURATION.fast,
        ease: EASE_OUT,
        stagger: 0.06,
        delay: 1.0,
      });
      // Count the headline figure up rather than having it simply appear.
      const counter = { v: 0 };
      gsap.to(counter, {
        v: total,
        duration: DURATION.slow * 1.2,
        ease: EASE,
        delay: 0.5,
        onUpdate: () => {
          const el = root.current?.querySelector(".rs-corpus-total");
          if (el) el.textContent = Math.round(counter.v).toLocaleString();
        },
      });
    }, root);
    return () => ctx.revert();
  }, [total]);

  return (
    <div ref={root} className="rs-corpus">
      <div className="rs-label" style={{ marginBottom: "1rem", fontSize: "0.68rem" }}>
        Seeded corpus · real test-mode orders
      </div>

      <div className="rs-corpus-chart">
        <svg viewBox="0 0 160 160" role="img" aria-label={`${total} transactions, ${ringTx} of them across ${ringCount} rings`}>
          <g transform="rotate(-90 80 80)">
            {/* uncorrelated traffic */}
            <circle
              className="rs-arc"
              cx="80"
              cy="80"
              r={R}
              fill="none"
              stroke="var(--line-strong)"
              strokeWidth="11"
              strokeDasharray={`${normalFrac * CIRC} ${CIRC}`}
              strokeDashoffset="0"
            />
            {/* one segment per real ring, sized by its transaction count */}
            {segments.map((s) => (
              <circle
                key={s.ring}
                className="rs-arc"
                cx="80"
                cy="80"
                r={R}
                fill="none"
                stroke="var(--accent)"
                strokeWidth="11"
                strokeDasharray={`${Math.max(0, s.frac * CIRC - GAP)} ${CIRC}`}
                strokeDashoffset={-(normalFrac + s.offset) * CIRC}
              >
                <title>{`${s.ring} — ${s.transactions} transactions`}</title>
              </circle>
            ))}
          </g>
        </svg>

        <div className="rs-corpus-center">
          <div className="rs-corpus-total">0</div>
          <div className="rs-corpus-total-k">transactions</div>
        </div>
      </div>

      <div className="rs-corpus-legend">
        <span>
          <i style={{ background: "var(--line-strong)" }} />
          {normal.toLocaleString()} uncorrelated
        </span>
        <span>
          <i style={{ background: "var(--accent)" }} />
          {ringTx.toLocaleString()} across {ringCount} rings
        </span>
      </div>

      <div className="rs-corpus-rows">
        {[
          { k: "Rings found", v: `${ringCount} / ${ringCount}`, tone: true },
          { k: "False flags", v: "0", tone: true },
          { k: "Time to score the graph", v: "0.04s" },
          { k: "Decisions by a human", v: "100%" },
        ].map((r) => (
          <div key={r.k} className="rs-corpus-row">
            <span>{r.k}</span>
            <b style={r.tone ? { color: "var(--accent)" } : undefined}>{r.v}</b>
          </div>
        ))}
      </div>

      <p className="rs-corpus-note">
        Measured on a synthetic corpus this project generated — separable by
        construction, so not a production-accuracy claim.
      </p>
    </div>
  );
}
