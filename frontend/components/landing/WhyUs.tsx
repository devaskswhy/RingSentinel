"use client";

/**
 * The pitch, and the numbers behind it.
 *
 * Every figure here is real and traceable: the detection results come from the
 * held-out evaluation, the runtime from the detector, the cost ratio from
 * scripts/monetization.py. The one number resting on an assumption is labelled
 * as such directly under it, because a pitch section is exactly where a project
 * is most tempted to launder an estimate into a fact.
 *
 * The comparison is framed as a STRUCTURAL gap, not a benchmark. No
 * per-transaction baseline was ever run here, so claiming one "catches 0%"
 * would be inventing a measurement. What can be said without inventing
 * anything is stronger anyway: a single transaction does not contain evidence
 * of coordination, so scoring it alone cannot find a ring however good the
 * model is. That is definitional.
 */

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { DURATION, EASE_OUT, prefersReducedMotion } from "@/lib/tokens";

const LACKS = [
  "Scores each payment on its own",
  "Sees only its own slice of the network",
  "Returns a number you cannot interrogate",
  "Acts automatically, then explains later",
];

const INSTEAD = [
  "Scores the cluster, never the payment",
  "Groups accounts by device, address and card",
  "Four named signals, with the entities behind each",
  "Flags and waits. A human decides, every time",
];

const STATS = [
  { n: "12 / 12", k: "rings found", s: "0 false flags" },
  { n: "0.04s", k: "to score the graph", s: "deterministic, same every run" },
  { n: "2,137×", k: "cheaper than per-transaction", s: "at 100k transactions/month" },
  { n: "100%", k: "decisions made by a human", s: "enforced by a database trigger" },
];

export default function WhyUs() {
  const root = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!root.current) return;
    // GSAP writes inline styles, so the CSS reduced-motion rule does not
    // reach it. The guard has to be here.
    if (prefersReducedMotion()) return;
    const ctx = gsap.context(() => {
      gsap.from(".rs-why-anim", {
        opacity: 0,
        y: 26,
        duration: DURATION.slow * 0.8,
        ease: EASE_OUT,
        stagger: 0.08,
        scrollTrigger: { trigger: root.current, start: "top 72%" },
      });
    }, root);
    // ctx.revert() kills these triggers on its own. Calling
    // ScrollTrigger.refresh() here as well forced a full layout recalculation
    // of every remaining trigger on the page for no benefit.
    return () => ctx.revert();
  }, []);

  return (
    <section
      ref={root}
      className="rs-why"
      style={{ borderTop: "1px solid var(--line)", padding: "8rem 0" }}
    >
      <div className="rs-shell">
        <div className="rs-why-anim rs-label" style={{ marginBottom: "2rem" }}>
          05 — why this
        </div>

        <h2 className="rs-why-anim rs-why-head">
          A ring is not a bad payment.
          <br />
          <span style={{ color: "var(--accent)" }}>It is a shape between them.</span>
        </h2>

        <p className="rs-why-anim rs-why-sub">
          Which is why a model that looks at one payment at a time cannot find
          one — not because it is a weak model, but because the evidence is not
          inside the thing it is looking at.
        </p>

        {/* ---- the gap ------------------------------------------------ */}
        <div className="rs-why-grid rs-why-anim">
          <div>
            <div className="rs-label" style={{ marginBottom: "1.4rem" }}>
              What a merchant has today
            </div>
            <ul className="rs-why-list" data-tone="lack">
              {LACKS.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </div>

          <div>
            <div className="rs-label" style={{ marginBottom: "1.4rem", color: "var(--accent)" }}>
              What RingSentinel does instead
            </div>
            <ul className="rs-why-list" data-tone="have">
              {INSTEAD.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </div>
        </div>

        {/* ---- the cost gap, drawn to scale --------------------------- */}
        <div className="rs-why-anim rs-why-cost">
          <div className="rs-label" style={{ marginBottom: "1.5rem" }}>
            Monthly model spend to scan 100,000 transactions
          </div>

          <div className="rs-cost-row">
            <span className="rs-cost-name">One model call per payment</span>
            <span className="rs-cost-bar"><span style={{ width: "100%" }} data-tone="lack" /></span>
            <span className="rs-cost-val">$160.00</span>
          </div>

          <div className="rs-cost-row">
            <span className="rs-cost-name">RingSentinel</span>
            {/* Drawn at a visible minimum: to scale this bar would be 0.3px. */}
            <span className="rs-cost-bar"><span style={{ width: "0.55%" }} data-tone="have" /></span>
            <span className="rs-cost-val" style={{ color: "var(--accent)" }}>$0.07</span>
          </div>

          <p className="rs-why-note">
            Case files are written per flagged cluster, not per payment, and
            detection makes no model calls at all. The second bar is drawn at a
            visible minimum — to scale it would be a third of a pixel.
          </p>
        </div>

        {/* ---- the measured results ----------------------------------- */}
        <div className="rs-why-anim rs-why-stats">
          {STATS.map((s) => (
            <div key={s.k}>
              <div className="rs-why-stat">{s.n}</div>
              <div className="rs-why-stat-k">{s.k}</div>
              <div className="rs-why-stat-s">{s.s}</div>
            </div>
          ))}
        </div>

        <p className="rs-why-anim rs-why-note" style={{ marginTop: "2.5rem" }}>
          Detection figures are measured on a synthetic corpus this project
          generated and are not a claim about production accuracy — the corpus is
          separable by construction, and BLINDSPOTS.md says where the detector is
          weakest. The cost ratio assumes 400 input tokens per payment for the
          comparison; every other number is observed.
        </p>
      </div>
    </section>
  );
}
