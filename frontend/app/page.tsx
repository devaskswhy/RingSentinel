"use client";

/**
 * Surface A — the landing page.
 *
 * Four beats, in order: the problem, the mechanism, the gate, the way in.
 * One pinned + scrubbed sequence carries beats one and two, because that is
 * where the argument lives; the rest are ordinary sections. Adding pinning to
 * all four would be motion for its own sake.
 *
 * Every animation uses EASE and DURATION from lib/tokens. Only transform,
 * opacity, and stroke-dashoffset are animated — never geometry.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import Loader from "@/components/landing/Loader";
import RingGraph, {
  RING_DOTS,
  gridPositions,
  ringPositions,
} from "@/components/landing/RingGraph";
import { initSmoothScroll, gsap, ScrollTrigger } from "@/lib/smoothScroll";
import {
  DURATION,
  EASE,
  EASE_OUT,
  MOBILE_BREAKPOINT,
  STAGGER,
} from "@/lib/tokens";

export default function Landing() {
  const [ready, setReady] = useState(false);
  const scope = useRef<HTMLDivElement>(null);
  const onLoaderDone = useCallback(() => setReady(true), []);

  useEffect(() => {
    if (!ready) return;

    const smooth = initSmoothScroll();

    // gsap.matchMedia rather than a one-off width check: it tears down and
    // re-runs the whole setup when the viewport or the motion preference
    // changes, so toggling device emulation in devtools switches to the mobile
    // path without a reload. A plain `window.innerWidth` read at mount would
    // leave a pinned desktop timeline running inside a phone viewport.
    const mm = gsap.matchMedia();
    const DESKTOP = `(min-width: ${MOBILE_BREAKPOINT}px) and (prefers-reduced-motion: no-preference)`;
    const REDUCED_OR_SMALL = `(max-width: ${MOBILE_BREAKPOINT - 1}px), (prefers-reduced-motion: reduce)`;

    const ctx = gsap.context(() => {
      // ---- Hero ---------------------------------------------------------
      gsap.from(".rs-hero-line", {
        yPercent: 110,
        opacity: 0,
        duration: DURATION.slow,
        ease: EASE_OUT,
        stagger: 0.08,
      });
      gsap.from(".rs-hero-sub", {
        opacity: 0,
        y: 16,
        duration: DURATION.slow * 0.7,
        ease: EASE_OUT,
        delay: 0.35,
      });

      // ---- The pinned sequence: scattered -> clustered -------------------
      //
      // Pinning is skipped under reduced motion and on narrow viewports. On a
      // phone a pinned scrub competes with the browser's own scroll handling
      // and the result janks; the sections simply play as static states there.
      mm.add(DESKTOP, () => {
        const tl = gsap.timeline({
          scrollTrigger: {
            trigger: ".rs-sequence",
            start: "top top",
            end: "+=2600",
            pin: true,
            scrub: 0.6,
            anticipatePin: 1,
          },
        });

        // Beat 1 -> 2: the caption swaps as the dots resolve.
        tl.to(".rs-cap-problem", { opacity: 0, y: -20, duration: 0.5, ease: EASE }, 0.5)
          .to(".rs-cap-mechanism", { opacity: 1, y: 0, duration: 0.6, ease: EASE }, 0.9);

        // Noise transactions recede — they were never part of it.
        tl.to(
          ".rs-dot-noise",
          { opacity: 0.12, scale: 0.6, duration: 0.8, ease: EASE, stagger: STAGGER },
          0.4,
        );

        // The seven ring accounts migrate into formation.
        gridPositions.slice(0, RING_DOTS).forEach((from, i) => {
          const to = ringPositions[i];
          tl.to(
            `.rs-dot[data-index="${i}"]`,
            {
              x: to.x - from.x,
              y: to.y - from.y,
              duration: 1.1,
              ease: EASE,
            },
            0.5 + i * 0.05,
          );
        });

        // The shared attributes appear, then the edges write themselves in.
        tl.to(".rs-hub", { opacity: 1, duration: 0.5, ease: EASE }, 1.5)
          .to(".rs-hub-glow", { opacity: 1, duration: 0.8, ease: EASE }, 1.6)
          .to(
            ".rs-edge",
            { strokeDashoffset: 0, duration: 0.9, ease: EASE, stagger: STAGGER },
            1.7,
          )
          .to(".rs-cap-mechanism", { opacity: 0, y: -20, duration: 0.5, ease: EASE }, 3.1)
          .to(".rs-cap-verdict", { opacity: 1, y: 0, duration: 0.6, ease: EASE }, 3.4);
      });

      // Small screens and reduced-motion users get the resolved state directly.
      // Pinning a scrubbed timeline on a phone fights the browser's own scroll
      // handling and janks; the argument reads perfectly well as a static image.
      mm.add(REDUCED_OR_SMALL, () => {
        gsap.set(".rs-dot-noise", { opacity: 0.12, scale: 0.6 });
        gridPositions.slice(0, RING_DOTS).forEach((from, i) => {
          const to = ringPositions[i];
          gsap.set(`.rs-dot[data-index="${i}"]`, {
            x: to.x - from.x,
            y: to.y - from.y,
          });
        });
        gsap.set(".rs-hub, .rs-hub-glow", { opacity: 1 });
        gsap.set(".rs-edge", { strokeDashoffset: 0 });
        gsap.set(".rs-cap-problem", { opacity: 0 });
        gsap.set(".rs-cap-mechanism", { opacity: 0 });
        gsap.set(".rs-cap-verdict", { opacity: 1, y: 0 });
      });

      // ---- The gate -----------------------------------------------------
      const gateVars = { opacity: 0, y: 28, duration: DURATION.slow * 0.8, ease: EASE_OUT };
      gsap.from(".rs-gate-item", {
        ...gateVars,
        stagger: 0.1,
        scrollTrigger: { trigger: ".rs-gate", start: "top 70%" },
      });

      gsap.from(".rs-cta-inner", {
        ...gateVars,
        scrollTrigger: { trigger: ".rs-cta", start: "top 75%" },
      });

      ScrollTrigger.refresh();
    }, scope);

    return () => {
      mm.revert();
      ctx.revert();
      smooth.destroy();
    };
  }, [ready]);

  return (
    <>
      {!ready && <Loader onDone={onLoaderDone} />}

      <div ref={scope}>
        <Nav />

        {/* ---- Hero ---------------------------------------------------- */}
        <section
          style={{
            minHeight: "100svh",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            padding: "0 clamp(1.5rem, 6vw, 7rem)",
            position: "relative",
          }}
        >
          <div className="rs-label" style={{ marginBottom: "1.75rem" }}>
            Razorpay buildathon · AI Risk Manager
          </div>

          <h1
            style={{
              fontSize: "clamp(2.6rem, 8.5vw, var(--step-7))",
              maxWidth: "16ch",
            }}
          >
            <span style={{ display: "block", overflow: "hidden" }}>
              <span className="rs-hero-line rs-anim" style={{ display: "block" }}>
                Fraud rings are
              </span>
            </span>
            <span style={{ display: "block", overflow: "hidden" }}>
              <span className="rs-hero-line rs-anim" style={{ display: "block" }}>
                invisible one
              </span>
            </span>
            <span style={{ display: "block", overflow: "hidden" }}>
              <span
                className="rs-hero-line rs-anim"
                style={{ display: "block", color: "var(--accent)" }}
              >
                transaction at a time.
              </span>
            </span>
          </h1>

          <p
            className="rs-hero-sub rs-anim"
            style={{
              marginTop: "2rem",
              maxWidth: "52ch",
              color: "var(--text-muted)",
              fontSize: "var(--step-1)",
            }}
          >
            RingSentinel does not score transactions. It builds a graph of which
            accounts share a device, an address, or a card — and flags the dense
            clusters that a per-transaction model cannot see.
          </p>

          <div
            className="rs-hero-sub rs-anim"
            style={{ marginTop: "3rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}
          >
            <Link href="/console" style={primaryButton}>
              Open the console →
            </Link>
            <a href="#mechanism" style={ghostButton}>
              See how it works
            </a>
          </div>

          <div
            className="rs-label"
            style={{ position: "absolute", bottom: "2.5rem", left: "clamp(1.5rem, 6vw, 7rem)" }}
          >
            Scroll
          </div>
        </section>

        {/* ---- Pinned sequence ----------------------------------------- */}
        <section
          id="mechanism"
          className="rs-sequence"
          style={{
            minHeight: "100svh",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            padding: "0 clamp(1.5rem, 6vw, 7rem)",
            overflow: "hidden",
          }}
        >
          <div style={{ position: "relative", minHeight: "8.5rem", maxWidth: "62ch" }}>
            <Caption
              className="rs-cap-problem"
              step="01 — the problem"
              title="Eighteen transactions. Every one of them approved."
              body="Scored individually, none of these crosses a threshold. Small amounts, valid cards, nothing out of policy. A per-transaction model clears all eighteen and moves on."
              initialOpacity={1}
            />
            <Caption
              className="rs-cap-mechanism"
              step="02 — the mechanism"
              title="The same eighteen, seen as a graph."
              body="Seven of them share a card and a device. Nothing new has been added — the data was always this shape. The connections were simply never looked at."
            />
            <Caption
              className="rs-cap-verdict"
              step="03 — the flag"
              title="That convergence is the whole signal."
              body="Seven accounts funnelling through two shared attributes, at 1.6-second intervals. RingSentinel scores the cluster, not the payment, and hands it to a human."
            />
          </div>

          <div style={{ marginTop: "1.5rem" }}>
            <RingGraph />
          </div>
        </section>

        {/* ---- The gate ------------------------------------------------ */}
        <section
          className="rs-gate"
          style={{
            minHeight: "100svh",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            padding: "6rem clamp(1.5rem, 6vw, 7rem)",
            borderTop: "1px solid var(--line)",
          }}
        >
          <div className="rs-gate-item rs-anim rs-label" style={{ marginBottom: "1.5rem" }}>
            04 — the gate
          </div>
          <h2
            className="rs-gate-item rs-anim"
            style={{ fontSize: "clamp(2rem, 5.5vw, var(--step-5))", maxWidth: "20ch" }}
          >
            Nothing executes
            <br />
            without a human.
          </h2>
          <p
            className="rs-gate-item rs-anim"
            style={{
              marginTop: "1.75rem",
              maxWidth: "56ch",
              color: "var(--text-muted)",
              fontSize: "var(--step-1)",
            }}
          >
            RingSentinel never blocks, freezes, or declines anything. It flags,
            explains, and waits. Claude writes the case file and recommends —
            it has no tool that could act, and the database refuses any status
            change that does not come from a human review.
          </p>

          <div
            style={{
              marginTop: "3.5rem",
              display: "grid",
              gap: "1px",
              gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
              background: "var(--line)",
              border: "1px solid var(--line)",
            }}
          >
            {[
              {
                k: "The detector",
                v: "Flags clusters as pending. It cannot set any other status.",
              },
              {
                k: "Claude",
                v: "Writes the explanation. Runs with zero tools — there is no function for it to call.",
              },
              {
                k: "The database",
                v: "Rejects any status change outside a human review transaction.",
              },
              {
                k: "The audit log",
                v: "Append-only, enforced by trigger. Decisions are never rewritten.",
              },
            ].map((item) => (
              <div
                key={item.k}
                className="rs-gate-item rs-anim"
                style={{ background: "var(--ink)", padding: "1.75rem 1.5rem" }}
              >
                <div
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: "var(--step-1)",
                    marginBottom: "0.6rem",
                  }}
                >
                  {item.k}
                </div>
                <div style={{ color: "var(--text-muted)", fontSize: "var(--step--1)" }}>
                  {item.v}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ---- CTA ----------------------------------------------------- */}
        <section
          className="rs-cta"
          style={{
            minHeight: "70svh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "6rem clamp(1.5rem, 6vw, 7rem)",
            borderTop: "1px solid var(--line)",
            textAlign: "center",
          }}
        >
          <div className="rs-cta-inner rs-anim">
            <h2 style={{ fontSize: "clamp(1.9rem, 5vw, var(--step-5))", maxWidth: "18ch", margin: "0 auto" }}>
              The console is live.
            </h2>
            <p
              style={{
                marginTop: "1.25rem",
                color: "var(--text-muted)",
                maxWidth: "48ch",
                marginInline: "auto",
              }}
            >
              Real clusters from 1,499 Razorpay test-mode transactions, each with
              a Claude case file and a human decision waiting.
            </p>
            <div style={{ marginTop: "2.5rem" }}>
              <Link href="/console" style={primaryButton}>
                Open the review console →
              </Link>
            </div>
          </div>
        </section>

        <footer
          style={{
            padding: "2rem clamp(1.5rem, 6vw, 7rem)",
            borderTop: "1px solid var(--line)",
            display: "flex",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "1rem",
          }}
        >
          <span className="rs-label">RingSentinel</span>
          <span className="rs-label">Razorpay test mode · nothing auto-blocks</span>
        </footer>
      </div>
    </>
  );
}

function Caption({
  className,
  step,
  title,
  body,
  initialOpacity = 0,
}: {
  className: string;
  step: string;
  title: string;
  body: string;
  initialOpacity?: number;
}) {
  return (
    <div
      className={`${className} rs-anim`}
      style={{
        position: "absolute",
        inset: 0,
        opacity: initialOpacity,
        transform: initialOpacity ? "none" : "translateY(20px)",
      }}
    >
      <div className="rs-label" style={{ marginBottom: "0.9rem" }}>
        {step}
      </div>
      <h2 style={{ fontSize: "clamp(1.5rem, 3.6vw, var(--step-4))", maxWidth: "24ch" }}>
        {title}
      </h2>
      <p
        style={{
          marginTop: "0.9rem",
          color: "var(--text-muted)",
          maxWidth: "56ch",
          fontSize: "var(--step-0)",
        }}
      >
        {body}
      </p>
    </div>
  );
}

function Nav() {
  return (
    <nav
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "1.25rem clamp(1.5rem, 6vw, 7rem)",
        backdropFilter: "blur(12px)",
        background: "rgba(8,9,10,0.6)",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-display)",
          fontWeight: 600,
          letterSpacing: "-0.02em",
        }}
      >
        Ring<span style={{ color: "var(--accent)" }}>Sentinel</span>
      </span>
      <Link
        href="/console"
        className="rs-focus"
        style={{
          color: "var(--text-muted)",
          textDecoration: "none",
          fontSize: "var(--step--1)",
          transition: `color var(--dur-fast) var(--ease)`,
        }}
      >
        Console →
      </Link>
    </nav>
  );
}

const primaryButton: React.CSSProperties = {
  display: "inline-block",
  padding: "0.85rem 1.6rem",
  background: "var(--accent)",
  color: "var(--ink)",
  fontWeight: 600,
  textDecoration: "none",
  fontSize: "var(--step-0)",
  transition: `transform var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease)`,
};

const ghostButton: React.CSSProperties = {
  display: "inline-block",
  padding: "0.85rem 1.6rem",
  border: "1px solid var(--line-strong)",
  color: "var(--text)",
  textDecoration: "none",
  fontSize: "var(--step-0)",
  transition: `border-color var(--dur-fast) var(--ease)`,
};
