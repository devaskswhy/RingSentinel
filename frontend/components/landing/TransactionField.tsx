"use client";

/**
 * The landing page's argument, drawn from the real corpus.
 *
 * Every dot is one of the 1,499 Razorpay test-mode transactions actually in the
 * database. 900 of them are uncorrelated background traffic and stay scattered
 * forever. The other 599 belong to the twelve rings the detector found, and on
 * scroll they migrate into formation around the attributes they share.
 *
 * This replaced eighteen hand-placed SVG dots. The thesis was always "nothing
 * is added, the data was always this shape" — with a hand-authored illustration
 * that is a claim, and at 1,499 real transactions it is a demonstration. The
 * shape on screen is a property of the corpus, not of a designer's arrangement.
 *
 * Structure of a ring, and why it is drawn this way: the hub is the shared
 * attribute, the ring of larger nodes around it are the accounts, and the small
 * dots are their transactions. Edges run hub-to-account, never hub-to-
 * transaction — a ring with 193 transactions would be an unreadable hairball,
 * and it is the ACCOUNTS converging on one attribute that is the actual signal.
 *
 * Canvas rather than SVG: 1,499 nodes is far past the point where the DOM stops
 * being the right tool. Dots are batched into two paths per frame and filled
 * once each, so the per-frame cost is nearly independent of the count.
 */

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";
import {
  ACCENT,
  ACCENT_RGB,
  MOBILE_BREAKPOINT,
  prefersReducedMotion,
} from "@/lib/tokens";

export interface CorpusShape {
  totals: { transactions: number; entities: number; entity_links: number };
  normal_transactions: number;
  rings: {
    ring: string;
    pattern: string;
    cadence: string;
    transactions: number;
    accounts: number;
  }[];
}

export interface FieldHandle {
  /** 0 = scattered, 1 = fully clustered. Driven by the scroll timeline. */
  setProgress: (p: number) => void;
}

/**
 * Used when the API cannot be reached. These are the real measured figures from
 * the seeded corpus (CLAUDE.md 5a), so the page still shows the true shape when
 * the backend is down — during judging, say. It is a fallback for availability,
 * not invented data.
 */
export const FALLBACK_CORPUS: CorpusShape = {
  totals: { transactions: 1499, entities: 635, entity_links: 4089 },
  normal_transactions: 900,
  rings: [
    { ring: "ring_01", pattern: "card_testing", cadence: "human", transactions: 36, accounts: 4 },
    { ring: "ring_02", pattern: "card_testing", cadence: "agent", transactions: 193, accounts: 7 },
    { ring: "ring_03", pattern: "promo_farming", cadence: "human", transactions: 22, accounts: 5 },
    { ring: "ring_04", pattern: "promo_farming", cadence: "agent", transactions: 41, accounts: 9 },
    { ring: "ring_05", pattern: "return_abuse", cadence: "human", transactions: 24, accounts: 4 },
    { ring: "ring_06", pattern: "return_abuse", cadence: "agent", transactions: 33, accounts: 5 },
    { ring: "ring_07", pattern: "card_testing", cadence: "human", transactions: 31, accounts: 3 },
    { ring: "ring_08", pattern: "promo_farming", cadence: "human", transactions: 26, accounts: 6 },
    { ring: "ring_09", pattern: "card_testing", cadence: "human", transactions: 58, accounts: 6 },
    { ring: "ring_10", pattern: "promo_farming", cadence: "agent", transactions: 62, accounts: 8 },
    { ring: "ring_11", pattern: "return_abuse", cadence: "human", transactions: 34, accounts: 4 },
    { ring: "ring_12", pattern: "return_abuse", cadence: "agent", transactions: 39, accounts: 5 },
  ],
};

/** Deterministic PRNG. The field must look identical on every reload. */
function mulberry32(seed: number) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const easeInOut = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

type Dot = {
  sx: number; sy: number;   // scattered position, unit space
  tx: number; ty: number;   // target position, unit space
  ring: number;             // -1 for background traffic
  drift: number;            // phase offset so idle motion is not synchronised
  delay: number;            // staggers the migration across the ring
};

type Hub = { x: number; y: number; accounts: { x: number; y: number }[]; ring: number };

/**
 * Positions are computed in a unit square and scaled at draw time, so a resize
 * never re-randomises the layout — it only re-scales it.
 */
function buildLayout(corpus: CorpusShape, density = 1) {
  const rand = mulberry32(0x5eed);
  const dots: Dot[] = [];
  const hubs: Hub[] = [];

  const ringCount = corpus.rings.length;
  const cols = Math.ceil(Math.sqrt(ringCount));
  const rows = Math.ceil(ringCount / cols);

  corpus.rings.forEach((ring, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    // Jittered grid of ring centres, inset from the edges.
    const cx = 0.14 + ((col + 0.5) / cols) * 0.72 + (rand() - 0.5) * 0.04;
    const cy = 0.16 + ((row + 0.5) / rows) * 0.68 + (rand() - 0.5) * 0.04;

    // Bigger rings get a slightly wider formation, saturating so a 193-
    // transaction ring does not swamp a 22-transaction one.
    const spread = 0.052 + 0.030 * (ring.accounts / (ring.accounts + 4));
    const accounts = Array.from({ length: ring.accounts }, (_, a) => {
      const angle = (a / ring.accounts) * Math.PI * 2 - Math.PI / 2;
      return {
        x: cx + Math.cos(angle) * spread,
        y: cy + Math.sin(angle) * spread * 0.86,
      };
    });
    hubs.push({ x: cx, y: cy, accounts, ring: index });

    const ringDots = Math.max(ring.accounts, Math.round(ring.transactions * density));
    for (let t = 0; t < ringDots; t++) {
      const account = accounts[t % ring.accounts];
      const angle = rand() * Math.PI * 2;
      const radius = (0.008 + rand() * 0.012) * (1 + (t % 3) * 0.15);
      dots.push({
        sx: rand(),
        sy: rand(),
        tx: account.x + Math.cos(angle) * radius,
        ty: account.y + Math.sin(angle) * radius * 0.9,
        ring: index,
        drift: rand() * Math.PI * 2,
        delay: (index / ringCount) * 0.18 + rand() * 0.12,
      });
    }
  });

  // Background traffic: scattered, and it stays scattered. These are the
  // transactions a per-transaction model would clear, correctly, one at a time.
  const normalDots = Math.round(corpus.normal_transactions * density);
  for (let i = 0; i < normalDots; i++) {
    const x = rand();
    const y = rand();
    dots.push({ sx: x, sy: y, tx: x, ty: y, ring: -1, drift: rand() * Math.PI * 2, delay: 0 });
  }

  return { dots, hubs };
}

const TransactionField = forwardRef<FieldHandle, { corpus: CorpusShape }>(
  function TransactionField({ corpus }, ref) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const progress = useRef(0);
    const pointer = useRef({ x: -999, y: -999 });
    // Drawn at full density on anything desktop-sized. Below that the dot count
    // is halved: the shape of the argument is identical and a mid-range phone
    // does not spend a frame budget it does not have.
    const density =
      typeof window !== "undefined" && window.innerWidth < MOBILE_BREAKPOINT ? 0.5 : 1;
    const layout = useMemo(() => buildLayout(corpus, density), [corpus, density]);

    useImperativeHandle(ref, () => ({
      setProgress: (p: number) => {
        progress.current = Math.max(0, Math.min(1, p));
      },
    }));

    useEffect(() => {
      const canvas = canvasRef.current;
      const parent = canvas?.parentElement;
      if (!canvas || !parent) return;
      const ctx = canvas.getContext("2d", { alpha: true });
      if (!ctx) return;

      const reduced = prefersReducedMotion();
      let width = 0;
      let height = 0;
      let raf = 0;
      let start = performance.now();
      // Drift time is held across pauses so the field does not jump when it
      // scrolls back into view.
      let elapsedHeld = 0;

      const resize = () => {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const rect = parent.getBoundingClientRect();
        width = rect.width;
        height = rect.height;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        if (reduced) draw(0);
      };

      function draw(elapsed: number) {
        if (!ctx) return;
        const p = reduced ? 1 : progress.current;
        ctx.clearRect(0, 0, width, height);

        const px = pointer.current.x;
        const py = pointer.current.y;

        // ---- dots, batched into two paths -----------------------------
        // One beginPath/fill per visual group rather than per dot: the whole
        // point of using canvas here. Per-frame cost barely moves with count.
        for (const group of [-1, 1] as const) {
          ctx.beginPath();
          for (const d of layout.dots) {
            const isRing = d.ring >= 0;
            if ((group === -1) === isRing) continue;

            // Each ring starts moving at its own moment, so the field resolves
            // in a wave rather than snapping all at once.
            const local = easeInOut(
              Math.max(0, Math.min(1, (p - d.delay) / (1 - d.delay || 1))),
            );
            const k = isRing ? local : 0;

            let x = (d.sx + (d.tx - d.sx) * k) * width;
            let y = (d.sy + (d.ty - d.sy) * k) * height;

            if (!reduced) {
              // Idle drift, so a settled field still breathes.
              const t = elapsed * 0.00018;
              const amp = isRing ? 1.1 - k * 0.75 : 1.6;
              x += Math.sin(t + d.drift) * amp;
              y += Math.cos(t * 0.9 + d.drift) * amp;

              // Cursor pushes nearby dots aside. Squared falloff, no sqrt in
              // the hot path until we know the dot is close enough to matter.
              const dx = x - px;
              const dy = y - py;
              const d2 = dx * dx + dy * dy;
              if (d2 < 14400) {
                const force = (1 - d2 / 14400) * 18;
                const dist = Math.sqrt(d2) || 1;
                x += (dx / dist) * force;
                y += (dy / dist) * force;
              }
            }

            const r = isRing ? 1.5 + k * 0.7 : 1.1;
            ctx.moveTo(x + r, y);
            ctx.arc(x, y, r, 0, Math.PI * 2);
          }
          if (group === -1) {
            // Background traffic recedes as the rings resolve — it was never
            // part of the story, and dimming it is the visual form of that.
            ctx.fillStyle = `rgba(154, 161, 168, ${0.34 - p * 0.2})`;
          } else {
            ctx.fillStyle = ACCENT;
            ctx.globalAlpha = 0.5 + p * 0.5;
          }
          ctx.fill();
          ctx.globalAlpha = 1;
        }

        if (p <= 0.02) return;

        // ---- edges: hub to account ------------------------------------
        ctx.strokeStyle = ACCENT;
        ctx.globalAlpha = Math.max(0, (p - 0.25) / 0.75) * 0.32;
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (const hub of layout.hubs) {
          for (const a of hub.accounts) {
            ctx.moveTo(hub.x * width, hub.y * height);
            ctx.lineTo(a.x * width, a.y * height);
          }
        }
        ctx.stroke();
        ctx.globalAlpha = 1;

        // ---- hubs: the shared attribute -------------------------------
        const hubAlpha = Math.max(0, (p - 0.35) / 0.65);
        if (hubAlpha > 0) {
          for (const hub of layout.hubs) {
            const x = hub.x * width;
            const y = hub.y * height;
            const glow = ctx.createRadialGradient(x, y, 0, x, y, 34);
            glow.addColorStop(0, `rgba(${ACCENT_RGB}, ${0.2 * hubAlpha})`);
            glow.addColorStop(1, `rgba(${ACCENT_RGB}, 0)`);
            ctx.fillStyle = glow;
            ctx.fillRect(x - 34, y - 34, 68, 68);

            ctx.save();
            ctx.translate(x, y);
            ctx.rotate(Math.PI / 4);
            ctx.fillStyle = ACCENT;
            ctx.globalAlpha = hubAlpha;
            const s = 4.2;
            ctx.fillRect(-s / 2, -s / 2, s, s);
            ctx.restore();
            ctx.globalAlpha = 1;
          }
        }
      }

      const loop = (now: number) => {
        draw(now - start);
        raf = requestAnimationFrame(loop);
      };

      const onPointer = (e: PointerEvent) => {
        const rect = canvas.getBoundingClientRect();
        pointer.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      };
      const onLeave = () => {
        pointer.current = { x: -999, y: -999 };
      };

      const observer = new ResizeObserver(resize);
      observer.observe(parent);
      resize();

      // The field animates only while it is on screen. Without this the RAF
      // loop ran for the entire session — through the whole rest of the page,
      // and in a background tab on some browsers — for a canvas nobody could
      // see. This is the single largest performance win on the page.
      const visibility = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting && !raf) {
            start = performance.now() - elapsedHeld;
            raf = requestAnimationFrame(loop);
          } else if (!entry.isIntersecting && raf) {
            elapsedHeld = performance.now() - start;
            cancelAnimationFrame(raf);
            raf = 0;
          }
        },
        { rootMargin: "200px" },
      );

      if (!reduced) {
        visibility.observe(parent);
        parent.addEventListener("pointermove", onPointer);
        parent.addEventListener("pointerleave", onLeave);
      }

      return () => {
        cancelAnimationFrame(raf);
        observer.disconnect();
        visibility.disconnect();
        parent.removeEventListener("pointermove", onPointer);
        parent.removeEventListener("pointerleave", onLeave);
      };
    }, [layout]);

    return (
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        style={{ display: "block", width: "100%", height: "100%" }}
      />
    );
  },
);

export default TransactionField;
