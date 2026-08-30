"use client";

/**
 * Drag the flag threshold and watch what it would cost.
 *
 * Everything above 0.30 is computed live from the twelve real cluster scores
 * the detector produced. Move the handle to 0.45 and three clusters genuinely
 * drop out, because 0.4204, 0.3761 and 0.3699 are their actual scores — not a
 * curve fitted for the demo.
 *
 * What it deliberately cannot do: go below 0.30. The detector only persists
 * clusters at or above SCORE_THRESHOLD, so there is no stored data on what a
 * lower threshold would flag, and inventing a false-positive count for that
 * region would be fabrication. The measured sweep is printed underneath
 * instead, labelled with the split it came from.
 *
 * The argument this makes is the one that matters about calibration: nothing
 * changes anywhere between 0.300 and 0.370. A threshold sitting in the middle
 * of a flat region is a measurement; one perched on a cliff is a fit.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { gsap } from "gsap";
import { DURATION, EASE_OUT, prefersReducedMotion } from "@/lib/tokens";

const MIN = 0.3;
const MAX = 0.6;
const FLAG_DEFAULT = 0.3;
const CONFIDENT = 0.45;

/**
 * The scores the detector actually produced, used when /clusters cannot be
 * reached. Real values, not placeholders — the landing page must not depend on
 * the backend being up.
 */
export const FALLBACK_SCORES = [
  0.8457, 0.8369, 0.8183, 0.7699, 0.7198, 0.7065,
  0.6733, 0.5769, 0.5744, 0.4204, 0.3761, 0.3699,
];

/**
 * The published sweep, from `scripts.evaluate_detection --sweep` on the TUNING
 * split (rings 1-8). Quoted rather than computed because the clusters below the
 * flag threshold were never stored.
 */
const MEASURED_SWEEP = [
  { t: "0.20", found: "8/8", fp: "1" },
  { t: "0.25 – 0.35", found: "8/8", fp: "0" },
  { t: "0.40", found: "6/8", fp: "0" },
];

export default function ThresholdScrubber({ scores }: { scores: number[] }) {
  const [t, setT] = useState(FLAG_DEFAULT);
  const root = useRef<HTMLElement>(null);

  const sorted = useMemo(() => [...scores].sort((a, b) => b - a), [scores]);
  const kept = sorted.filter((s) => s >= t);
  const lost = sorted.filter((s) => s < t);
  const ambiguous = kept.filter((s) => s < CONFIDENT);

  // The flat region: how far the threshold can travel before anything changes.
  const weakest = sorted[sorted.length - 1] ?? MIN;
  const plateau = Math.max(0, weakest - FLAG_DEFAULT);

  const pct = (v: number) => ((v - MIN) / (MAX - MIN)) * 100;

  useEffect(() => {
    if (!root.current) return;
    // GSAP writes inline styles, so the CSS reduced-motion rule does not
    // reach it. The guard has to be here.
    if (prefersReducedMotion()) return;
    const ctx = gsap.context(() => {
      gsap.from(".rs-thr-anim", {
        opacity: 0,
        y: 24,
        duration: DURATION.slow * 0.7,
        ease: EASE_OUT,
        stagger: 0.08,
        scrollTrigger: { trigger: root.current, start: "top 75%" },
      });
    }, root);
    // ctx.revert() kills these triggers on its own. Calling
    // ScrollTrigger.refresh() here as well forced a full layout recalculation
    // of every remaining trigger on the page for no benefit.
    return () => ctx.revert();
  }, []);

  return (
    <section ref={root} className="rs-thr" style={{ borderTop: "1px solid var(--line)" }}>
      <div className="rs-shell">
        <div className="rs-thr-anim rs-label" style={{ marginBottom: "2rem" }}>
          06 — calibration
        </div>

        <h2 className="rs-thr-anim rs-why-head">
          The threshold was measured,
          <br />
          <span style={{ color: "var(--accent)" }}>not chosen.</span>
        </h2>

        <p className="rs-thr-anim rs-why-sub">
          Drag it. Every tick is a real cluster the detector scored — move the
          handle past one and that ring stops being flagged.
        </p>

        <div className="rs-thr-anim rs-thr-panel">
          <div className="rs-thr-readout">
            <div>
              <div className="rs-thr-big">{t.toFixed(3)}</div>
              <div className="rs-label">flag threshold</div>
            </div>
            <div>
              <div className="rs-thr-big" style={{ color: "var(--accent)" }}>
                {kept.length}
                <span style={{ color: "var(--text-faint)" }}> / {sorted.length}</span>
              </div>
              <div className="rs-label">rings still flagged</div>
            </div>
            <div>
              <div
                className="rs-thr-big"
                style={{ color: lost.length ? "var(--danger)" : "var(--text)" }}
              >
                {lost.length}
              </div>
              <div className="rs-label">rings missed</div>
            </div>
            <div>
              <div
                className="rs-thr-big"
                style={{ color: ambiguous.length ? "var(--signal)" : "var(--text)" }}
              >
                {ambiguous.length}
              </div>
              <div className="rs-label">in the ambiguous band</div>
            </div>
          </div>

          <div className="rs-thr-track-wrap">
            {/* the twelve real scores, as ticks */}
            <div className="rs-thr-ticks" aria-hidden="true">
              {sorted.map((s, i) => (
                <span
                  key={`${s}-${i}`}
                  className="rs-thr-tick"
                  data-lost={s < t}
                  style={{ left: `${Math.min(100, Math.max(0, pct(s)))}%` }}
                  title={`cluster scored ${s.toFixed(4)}`}
                />
              ))}
              {/* the confidence threshold, which does not move */}
              <span className="rs-thr-conf" style={{ left: `${pct(CONFIDENT)}%` }}>
                <span>0.45 confidence</span>
              </span>
            </div>

            <input
              type="range"
              min={MIN}
              max={MAX}
              step={0.001}
              value={t}
              onChange={(e) => setT(Number(e.target.value))}
              className="rs-thr-range rs-focus"
              aria-label="Flag threshold"
              aria-valuetext={`${t.toFixed(3)}, ${kept.length} of ${sorted.length} rings flagged`}
            />

            <div className="rs-thr-scale">
              <span>{MIN.toFixed(2)}</span>
              <span>{MAX.toFixed(2)}</span>
            </div>
          </div>

          <p className="rs-thr-verdict">
            {lost.length === 0 ? (
              <>
                Nothing changes anywhere between{" "}
                <b>{FLAG_DEFAULT.toFixed(3)}</b> and <b>{weakest.toFixed(3)}</b>. That{" "}
                <b>{plateau.toFixed(3)}</b> of slack is the margin — a threshold sitting
                in the middle of a flat region is a measurement, one perched on a
                cliff is a fit.
              </>
            ) : (
              <>
                {lost.length === 1 ? "One ring" : `${lost.length} rings`} would go
                unflagged at this threshold — the weakest scored{" "}
                <b>{lost[0].toFixed(4)}</b>. Every one of them is a real ring the
                detector found at 0.300.
              </>
            )}
          </p>
        </div>

        <div className="rs-thr-anim rs-thr-measured">
          <div className="rs-label" style={{ marginBottom: "1.1rem" }}>
            Below 0.30 · measured, not computed
          </div>
          <div className="rs-thr-sweep">
            {MEASURED_SWEEP.map((r) => (
              <div key={r.t}>
                <span className="rs-mono">{r.t}</span>
                <span>
                  {r.found} rings · {r.fp} false flag{r.fp === "1" ? "" : "s"}
                </span>
              </div>
            ))}
          </div>
          <p className="rs-why-note">
            The slider stops at 0.30 because the detector only stores clusters at
            or above it — there is no record of what a lower threshold would have
            flagged, and putting a number there would be inventing one. These
            three rows come from the published sweep on the tuning split (rings
            1–8), run long before the held-out rings were opened. 0.30 sits in
            the centre of the stable band, which is why it was picked.
          </p>
        </div>
      </div>
    </section>
  );
}
