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

/**
 * Three functional colours, each with exactly one meaning, plus a neutral ramp.
 *
 *   accent  a confirmed finding, and interactive affordances
 *   signal  a human needs to look at this (the ambiguous band)
 *   danger  an operation failed
 *
 * This file used to claim "the single accent, there is deliberately no second
 * one" while defining eleven hues fifty lines further down. Three colours that
 * each mean one thing is a rule that can actually be kept; one colour was a
 * rule that got quietly broken and left the claim standing.
 */
export const ACCENT = "#2dd4bf";
export const ACCENT_DIM = "#14b8a6";
export const DANGER = "#e5484d";
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
 *   fast — anything small and frequent: buttons, rows, tags.
 *   slow — full-section transitions on the landing page.
 * Anything in between is a decision nobody needs to make.
 */
export const DURATION = {
  fast: 0.25,
  slow: 1.0,
} as const;

/** Stagger for list entrances. Small enough to read as one motion. */
export const STAGGER = 0.04;

/**
 * Reserved strictly for "a human needs to look at this" — the ambiguous band,
 * and nothing else. The moment it appears somewhere routine it stops meaning
 * anything.
 */
export const SIGNAL = "#e8a33d";

/**
 * ---------------------------------------------------------------------------
 * Tags replace the old coloured pills.
 *
 * This used to be eleven distinct hues — red-300, blue-300, amber-300,
 * violet-300, indigo-400, pink-400 and friends. That is the stock Tailwind
 * palette, it is the single most recognisable fingerprint of a generated
 * interface, and it flatly contradicted the rule this file states two lines
 * from the top. It also meant three differently-coloured pills in one table
 * row, which is decoration rather than information.
 *
 * A real instrument differentiates by POSITION, LABEL and LUMINANCE, because
 * those survive a colourblind reviewer and a projector with bad gamma. Hue is
 * spent on exactly one thing: whether something needs attention.
 * ---------------------------------------------------------------------------
 */
export type Tone = "bright" | "neutral" | "faint" | "accent" | "signal";

export const TONE_COLOR: Record<Tone, string> = {
  bright: "var(--text)",
  neutral: "var(--text-muted)",
  faint: "var(--text-faint)",
  accent: "var(--accent)",
  signal: "var(--signal)",
};

/** Cadence. "AGENT" earns the accent because it is the discriminating finding. */
export const CADENCE_TAG = {
  agent_like: { label: "AGENT", tone: "accent" as Tone },
  human_like: { label: "HUMAN", tone: "neutral" as Tone },
  inconclusive: { label: "UNCLEAR", tone: "faint" as Tone },
} as const;

/**
 * Status. `needs_review` reads as AMBIGUOUS because that is what it means —
 * the detector flagged it and said it was unsure (CLAUDE.md 5e). It is the one
 * state that carries the signal hue.
 */
export const STATUS_TAG = {
  pending: { label: "PENDING", tone: "bright" as Tone },
  needs_review: { label: "AMBIGUOUS", tone: "signal" as Tone },
  cleared: { label: "APPROVED", tone: "accent" as Tone },
  dismissed: { label: "DISMISSED", tone: "faint" as Tone },
} as const;

/** Claude's recommendation. Advisory, so it never outweighs the score. */
export const ACTION_TAG = {
  likely_ring: { label: "RING", tone: "bright" as Tone },
  review_closer: { label: "CLOSER", tone: "signal" as Tone },
  likely_false_positive: { label: "FALSE POS", tone: "faint" as Tone },
} as const;

/**
 * Graph nodes: accounts in the accent, attributes on a luminance ramp.
 *
 * Four hues became one hue plus three greys. The entity types are already
 * distinguished by SHAPE in both graphs — circles for accounts, diamonds for
 * shared attributes — so hue was carrying no information the shape did not
 * already carry, and four saturated colours on a dark field read as a
 * children's toy rather than an instrument.
 */
export const NODE_COLORS = {
  customer: "#2dd4bf",
  instrument: "#e8eaed",
  device: "#9aa1a8",
  address: "#656c73",
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
