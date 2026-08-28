/**
 * Design tokens — defined once, imported by both surfaces.
 *
 * The CSS-facing half of these lives in `app/globals.css` as custom properties.
 * This file is the JavaScript mirror, for GSAP, which needs real numbers rather
 * than CSS variable strings.
 *
 * Rule: never invent an easing curve or a duration inline. If a value is not
 * here, it does not get used.
 */

/** The single accent. There is deliberately no second one. */
export const ACCENT = "#2dd4bf";
export const ACCENT_DIM = "#14b8a6";
export const INK = "#08090a";

/**
 * One easing curve for the whole product. `power3.inOut` is slow at both ends
 * and quick through the middle, which reads as deliberate rather than bouncy —
 * right for a tool about fraud review.
 */
export const EASE = "power3.inOut";

/** Entrances only, where starting fast and settling feels better than symmetry. */
export const EASE_OUT = "power3.out";

/**
 * Two speeds, not a spectrum.
 *   fast — anything small and frequent: buttons, rows, pills.
 *   slow — full-section transitions on the landing page.
 * Anything in between is a decision nobody needs to make.
 */
export const DURATION = {
  fast: 0.25,
  slow: 1.0,
} as const;

/** Stagger for list entrances. Small enough to read as one motion. */
export const STAGGER = 0.04;

/** Cadence classes get a colour each. Teal stays reserved for the accent. */
export const CADENCE_COLORS = {
  agent_like: { fg: "#fca5a5", bg: "rgba(239,68,68,0.12)", border: "rgba(239,68,68,0.3)" },
  human_like: { fg: "#93c5fd", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.3)" },
  inconclusive: { fg: "#a1a1aa", bg: "rgba(161,161,170,0.1)", border: "rgba(161,161,170,0.25)" },
} as const;

export const STATUS_COLORS = {
  pending: { fg: "#fcd34d", bg: "rgba(245,158,11,0.12)" },
  cleared: { fg: "#2dd4bf", bg: "rgba(45,212,191,0.12)" },
  dismissed: { fg: "#a1a1aa", bg: "rgba(161,161,170,0.1)" },
  needs_review: { fg: "#c4b5fd", bg: "rgba(139,92,246,0.12)" },
} as const;

/** Graph node colours, one per entity type. */
export const NODE_COLORS = {
  customer: "#2dd4bf",
  device: "#818cf8",
  address: "#fbbf24",
  instrument: "#f472b6",
} as const;

/**
 * Reduced motion is a preference, not an edge case. Both surfaces check this
 * and drop pinning, scrubbing, and long transitions when it is set.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Landing page drops the expensive work below this width. */
export const MOBILE_BREAKPOINT = 768;

export function isMobileViewport(): boolean {
  if (typeof window === "undefined") return false;
  return window.innerWidth < MOBILE_BREAKPOINT;
}
