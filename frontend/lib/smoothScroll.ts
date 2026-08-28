"use client";

/**
 * Lenis wired to GSAP ScrollTrigger — one scroll system, not two.
 *
 * The failure mode this avoids: Lenis interpolates scroll position on its own
 * RAF loop while ScrollTrigger reads `window.scrollY` on GSAP's ticker. Two
 * loops sampling at different moments produces pinned sections that lag, jitter,
 * or overshoot. Three lines fix it:
 *
 *   1. `lenis.on("scroll", ScrollTrigger.update)` — ScrollTrigger recalculates
 *      when Lenis actually moves, not when the browser fires a scroll event.
 *   2. `gsap.ticker.add(t => lenis.raf(t * 1000))` — Lenis advances on GSAP's
 *      ticker, so there is a single RAF loop. GSAP passes seconds, Lenis wants
 *      milliseconds.
 *   3. `gsap.ticker.lagSmoothing(0)` — GSAP's lag smoothing rewrites elapsed
 *      time after a frame drop, which desynchronises the scrub.
 *
 * Only used by the landing page. The console scrolls natively: a reviewer
 * hitting page-down wants the row where they expect it, not an eased glide.
 */

import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import { prefersReducedMotion } from "./tokens";

let lenis: Lenis | null = null;
let registered = false;

export function registerGsap() {
  if (registered || typeof window === "undefined") return;
  gsap.registerPlugin(ScrollTrigger);
  registered = true;
}

export interface SmoothScrollHandle {
  lenis: Lenis | null;
  destroy: () => void;
}

export function initSmoothScroll(): SmoothScrollHandle {
  registerGsap();

  // With reduced motion set, native scrolling is the correct behaviour. Bail
  // out entirely rather than shipping a "gentler" smooth scroll.
  if (prefersReducedMotion()) {
    return { lenis: null, destroy: () => {} };
  }

  lenis = new Lenis({
    duration: 1.05,
    // Matches the CSS/GSAP easing family so the page decelerates the same way
    // its animations do.
    easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
    smoothWheel: true,
    // Touch devices already have momentum scrolling; adding Lenis on top of it
    // fights the platform and feels worse than doing nothing.
    syncTouch: false,
  });

  const onScroll = () => ScrollTrigger.update();
  lenis.on("scroll", onScroll);

  const raf = (time: number) => {
    lenis?.raf(time * 1000);
  };
  gsap.ticker.add(raf);
  gsap.ticker.lagSmoothing(0);

  return {
    lenis,
    destroy: () => {
      lenis?.off("scroll", onScroll);
      gsap.ticker.remove(raf);
      gsap.ticker.lagSmoothing(500, 33);
      lenis?.destroy();
      lenis = null;
      ScrollTrigger.getAll().forEach((t) => t.kill());
    },
  };
}

export function getLenis() {
  return lenis;
}

export { gsap, ScrollTrigger };
