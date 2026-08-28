"use client";

/**
 * Intro loader: a 0–100 counter and a wipe. Nothing more.
 *
 * Held to ~1.9s even when assets are already cached, because a loader that
 * vanishes instantly reads as a flash of broken layout. Capped well under the
 * 2.5s ceiling — past that it stops being an entrance and becomes a queue.
 *
 * Skipped entirely under reduced motion.
 */

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { DURATION, EASE, prefersReducedMotion } from "@/lib/tokens";

const HOLD_SECONDS = 1.9;

export default function Loader({ onDone }: { onDone: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (prefersReducedMotion()) {
      onDone();
      return;
    }

    const counter = { value: 0 };
    const tl = gsap.timeline({ onComplete: onDone });

    tl.to(counter, {
      value: 100,
      duration: HOLD_SECONDS,
      ease: EASE,
      onUpdate: () => setCount(Math.round(counter.value)),
    })
      .to(
        ".rs-loader-bar",
        { scaleX: 1, duration: HOLD_SECONDS, ease: EASE },
        0,
      )
      // Wipe upward rather than fading: a fade leaves the page looking washed
      // out mid-transition, a wipe hands off cleanly.
      .to(root.current, {
        yPercent: -100,
        duration: DURATION.slow * 0.8,
        ease: EASE,
      })
      .set(root.current, { display: "none" });

    return () => {
      tl.kill();
    };
  }, [onDone]);

  return (
    <div
      ref={root}
      className="rs-anim"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        background: "var(--ink)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "2rem",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <div className="rs-label" style={{ marginBottom: "0.75rem" }}>
          RingSentinel
        </div>
        <div
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "var(--step-6)",
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "-0.04em",
            color: "var(--text)",
          }}
        >
          {String(count).padStart(3, "0")}
        </div>
      </div>

      <div
        style={{
          width: "min(320px, 60vw)",
          height: 1,
          background: "var(--line-strong)",
          overflow: "hidden",
        }}
      >
        <div
          className="rs-loader-bar rs-anim"
          style={{
            height: "100%",
            background: "var(--accent)",
            transform: "scaleX(0)",
            transformOrigin: "left center",
          }}
        />
      </div>
    </div>
  );
}
