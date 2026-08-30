"use client";

/**
 * What this page is, what to do on it, and what it deliberately will not do.
 *
 * The console assumed its reader already knew all of that. An analyst who uses
 * it daily does; a judge opening it cold sees a table and a panel and has to
 * infer the argument. This panel states it — the pipeline, the review order,
 * and the four claims worth arguing with.
 *
 * It collapses, and the choice is remembered. Someone working the queue does
 * not want a manual above it every morning, and someone seeing it for the
 * first time should not have to hunt for the point.
 */

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { DURATION, EASE_OUT, STAGGER } from "@/lib/tokens";

const STORAGE_KEY = "ringsentinel.orientation.collapsed";

/** The pipeline. The bracketed step is the only one a human performs. */
const PIPELINE = [
  { k: "Razorpay orders", v: "real test-mode webhooks" },
  { k: "Entity graph", v: "shared device · address · card" },
  { k: "Four signals", v: "deterministic, no model" },
  { k: "Claude", v: "explains, cannot act" },
  { k: "Human decides", v: "the only decision point", gate: true },
  { k: "Audit", v: "append-only, hash-chained" },
];

/** Maps 1:1 onto the numbered sections in the detail panel. */
const REVIEW_STEPS = [
  "Read the case file — Claude's plain-language account of the cluster.",
  "Check the four signals — every score decomposes into named parts.",
  "See how close it was — what smallest change would flip it.",
  "Look at the graph — which accounts share which attribute.",
  "Decide, with a written reason. The reason is required by the schema.",
  "The audit trail records who decided and why. It cannot be rewritten.",
  "Verify the chain — rebuild the evidence pack and re-check every row.",
];

const CLAIMS: { label: string; title: string; body: string; tone?: "gate" }[] = [
  {
    label: "What a per-transaction model misses",
    title: "Every one of these orders is individually unremarkable.",
    body:
      "Small amounts, valid cards, nothing out of policy — scored alone, none of them crosses a threshold, and a per-transaction model correctly clears all 1,499. Coordination does not exist inside a transaction. It exists between them, which is precisely what scoring one at a time cannot see.",
  },
  {
    label: "Where this makes the difference",
    title: "The score is a sum of named parts, not a model output.",
    body:
      "Attribute reuse, timing regularity, concentration, account shallowness — with the exact entities that drove each one. That is why a reviewer can argue with a number instead of trusting it, and why the console can tell you what smallest change would have flipped the verdict. A model output cannot be interrogated that way.",
  },
  {
    label: "What it will never do",
    title: "Nothing here can block, freeze, or decline anyone.",
    body:
      "No such code path exists to call. A Postgres trigger rejects any status change made outside a human review carrying a written reason of at least five characters, and refuses to revise a decision once recorded. Claude runs with zero tools — there is no function for it to invoke even if the prompt were subverted.",
    tone: "gate",
  },
  {
    label: "What it becomes next",
    title: "Rings cross merchant boundaries. One merchant sees one slice.",
    body:
      "The crew testing cards on one storefront is farming promos on another. Because entity references are salted opaque tokens and never raw PII, two merchants can compare hashed device and card references without either learning who the other's customers are — a cross-merchant graph that only an aggregator sitting across many merchants could assemble.",
  },
];

export default function Orientation() {
  // Starts expanded, which is also what the server renders.
  //
  // The alternative — render nothing until the stored preference is known —
  // avoids a collapse flicker for return visitors but leaves the panel absent
  // from the HTML and blank until hydration. Most people opening this console
  // are seeing it for the first time and have no stored preference at all, so
  // the trade goes the other way: server-render the explanation, and let a
  // returning reviewer's collapse apply a frame later.
  const [collapsed, setCollapsed] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  // Storage can throw in a private window or with site data blocked, so a
  // failure just means "show it" rather than a broken page.
  useEffect(() => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY) === "1") setCollapsed(true);
    } catch {
      /* stay open */
    }
  }, []);

  useEffect(() => {
    if (collapsed || !root.current) return;
    const ctx = gsap.context(() => {
      gsap.from(".rs-orient-item", {
        opacity: 0,
        y: 10,
        duration: DURATION.fast,
        ease: EASE_OUT,
        stagger: STAGGER,
      });
    }, root);
    return () => ctx.revert();
  }, [collapsed]);

  function toggle() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      /* the preference simply will not persist */
    }
  }

  return (
    <div
      ref={root}
      className="rs-rule-b"
      style={{ background: "var(--ink-raised)" }}
    >
      <div style={{ padding: collapsed ? "0.7rem 1.5rem" : "1.35rem 1.5rem 1.6rem" }}>
        <button
          onClick={toggle}
          className="rs-focus"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.7rem",
            width: "100%",
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            color: "var(--text)",
            textAlign: "left",
          }}
          aria-expanded={!collapsed}
        >
          <span className="rs-label" style={{ color: "var(--accent)" }}>
            How this works
          </span>
          <span
            style={{ flex: 1, height: 1, background: "var(--line)" }}
            aria-hidden="true"
          />
          <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
            {collapsed ? "show ▾" : "hide ▴"}
          </span>
        </button>

        {!collapsed && (
          <>
            {/* ---- the pipeline ------------------------------------- */}
            <div
              className="rs-orient-item rs-pipeline"
              style={{ marginTop: "1.3rem" }}
            >
              {PIPELINE.map((s, i) => (
                <div key={s.k} className="rs-pipeline-step" data-gate={s.gate ?? false}>
                  <div
                    className="rs-mono"
                    style={{
                      color: s.gate ? "var(--accent)" : "var(--text)",
                      fontWeight: 500,
                      letterSpacing: "0.02em",
                    }}
                  >
                    {s.gate ? `▐ ${s.k}` : s.k}
                  </div>
                  <div
                    style={{
                      color: "var(--text-faint)",
                      fontSize: "var(--console-small)",
                      marginTop: "0.2rem",
                    }}
                  >
                    {s.v}
                  </div>
                  {i < PIPELINE.length - 1 && (
                    <span className="rs-pipeline-arrow" aria-hidden="true">
                      →
                    </span>
                  )}
                </div>
              ))}
            </div>

            <p
              className="rs-orient-item"
              style={{
                margin: "0.9rem 0 0",
                color: "var(--text-muted)",
                fontSize: "var(--console-small)",
                maxWidth: "94ch",
              }}
            >
              Detection is deterministic — NetworkX and arithmetic, the same
              answer every run. Claude is used for exactly one thing, the
              plain-language case file, and it has no authority beyond writing
              it. The bracketed step is the only place anything is decided.
            </p>

            {/* ---- what to do here ---------------------------------- */}
            <div className="rs-orient-item" style={{ marginTop: "1.6rem" }}>
              <div className="rs-label" style={{ marginBottom: "0.7rem" }}>
                Reviewing a cluster — the numbered steps in the panel on the right
              </div>
              <ol className="rs-orient-steps">
                {REVIEW_STEPS.map((s, i) => (
                  <li key={i}>
                    <span className="rs-mono" style={{ color: "var(--accent)" }}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span>{s}</span>
                  </li>
                ))}
              </ol>
            </div>

            {/* ---- the four claims ---------------------------------- */}
            <div className="rs-orient-item rs-orient-claims">
              {CLAIMS.map((c) => (
                <div
                  key={c.label}
                  style={{
                    background: "var(--ink)",
                    padding: "1.1rem 1.2rem",
                    borderTop: `2px solid ${
                      c.tone === "gate" ? "var(--accent)" : "var(--line-strong)"
                    }`,
                  }}
                >
                  <div className="rs-label" style={{ marginBottom: "0.55rem" }}>
                    {c.label}
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-display)",
                      fontSize: "var(--step-1)",
                      lineHeight: 1.25,
                      marginBottom: "0.6rem",
                    }}
                  >
                    {c.title}
                  </div>
                  <p
                    style={{
                      margin: 0,
                      color: "var(--text-muted)",
                      fontSize: "var(--console-small)",
                      lineHeight: 1.6,
                    }}
                  >
                    {c.body}
                  </p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
