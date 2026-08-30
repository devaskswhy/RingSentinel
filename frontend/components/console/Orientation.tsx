"use client";

/**
 * What this page is, in as few words as it can be made.
 *
 * The first version of this panel was a wall: four sixty-word paragraphs side
 * by side, seven numbered steps in two columns, a pipeline and a paragraph
 * about it. Every sentence was true and the whole thing was unreadable — a
 * first-time visitor cannot absorb that much prose before they have any reason
 * to care, and the density made it look like documentation rather than an
 * explanation.
 *
 * Rebuilt around one rule: nothing here may be longer than a glance. One
 * headline, one diagram, four claims of one line each. The detail already lives
 * in the panel on the right and in the repo — this only has to make someone
 * understand what they are looking at.
 */

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { DURATION, EASE_OUT, STAGGER } from "@/lib/tokens";
import ThesisDiagram from "./ThesisDiagram";

const STORAGE_KEY = "ringsentinel.orientation.collapsed";

/** The pipeline. The bracketed step is the only one a human performs. */
const PIPELINE = [
  "Razorpay orders",
  "Entity graph",
  "Four signals",
  "Claude explains",
  "Human decides",
  "Audit",
];
const GATE_INDEX = 4;

/** One line each. If it needs a paragraph it does not belong here. */
const CLAIMS = [
  { label: "What others miss", line: "Coordination lives between transactions, not inside one." },
  { label: "What we do", line: "Every score breaks into four named parts you can argue with." },
  { label: "What we never do", line: "Nothing here can block anyone. A database trigger enforces it." },
  { label: "What's next", line: "Rings cross merchants. Salted tokens let us see across them." },
];

export default function Orientation() {
  // Starts expanded, which is also what the server renders — most people
  // opening this console have no stored preference at all.
  const [collapsed, setCollapsed] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY) === "1") setCollapsed(true);
    } catch {
      /* storage can throw in a private window; stay open */
    }
  }, []);

  useEffect(() => {
    if (collapsed || !root.current) return;
    const ctx = gsap.context(() => {
      gsap.from(".rs-orient-item", {
        opacity: 0,
        y: 12,
        duration: DURATION.fast,
        ease: EASE_OUT,
        stagger: STAGGER * 2,
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
    <div ref={root} className="rs-rule-b" style={{ background: "var(--ink-raised)" }}>
      <div className={collapsed ? "rs-orient rs-orient-shut" : "rs-orient"}>
        <button onClick={toggle} className="rs-orient-toggle rs-focus" aria-expanded={!collapsed}>
          <span className="rs-label" style={{ color: "var(--accent)" }}>
            How this works
          </span>
          <span style={{ flex: 1, height: 1, background: "var(--line)" }} aria-hidden="true" />
          <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
            {collapsed ? "show" : "hide"}
          </span>
        </button>

        {!collapsed && (
          <>
            <div className="rs-orient-hero">
              <div className="rs-orient-item">
                <h2 className="rs-orient-head">
                  Fraud rings are invisible
                  <br />
                  one transaction at a time.
                </h2>
                <p className="rs-orient-sub">
                  So this scores the cluster, never the payment — and hands every
                  one to a human.
                </p>
              </div>

              <div className="rs-orient-item rs-orient-figure">
                <ThesisDiagram />
              </div>
            </div>

            <div className="rs-orient-item rs-orient-pipe">
              {PIPELINE.map((step, i) => (
                <span key={step} className="rs-pipe-step" data-gate={i === GATE_INDEX}>
                  {step}
                </span>
              ))}
            </div>

            <div className="rs-orient-item rs-orient-claims">
              {CLAIMS.map((c) => (
                <div key={c.label} className="rs-claim">
                  <div className="rs-label">{c.label}</div>
                  <p>{c.line}</p>
                </div>
              ))}
            </div>

            <p className="rs-orient-item rs-orient-foot">
              Pick a cluster below. The panel walks you through it in seven
              numbered steps, ending in a decision only you can make.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
