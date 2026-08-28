"use client";

/**
 * The landing page's one piece of real animation.
 *
 * It is deliberately the same eighteen dots throughout. In the scattered state
 * they are eighteen transactions, each individually unremarkable — which is
 * exactly what a per-transaction model sees. On scroll, seven of them move into
 * a ring around two shared attributes and the edges draw in. Nothing new is
 * introduced; the data was always this shape.
 *
 * Plain SVG. A force simulation or WebGL would cost load time and buy nothing
 * here — the layout is fixed, so it may as well be computed once at module
 * scope and animated with transforms.
 */

import { forwardRef } from "react";
import { NODE_COLORS } from "@/lib/tokens";

const VIEW_W = 1000;
const VIEW_H = 560;

export const DOT_COUNT = 18;
export const RING_DOTS = 7;

/** Scattered state: an even grid. Six across, three down. */
export const gridPositions = Array.from({ length: DOT_COUNT }, (_, i) => {
  const col = i % 6;
  const row = Math.floor(i / 6);
  return { x: 140 + col * 144, y: 150 + row * 130 };
});

/** Clustered state: seven accounts in a circle around two shared attributes. */
const CENTER = { x: 500, y: 280 };
const RADIUS = 165;

export const ringPositions = Array.from({ length: RING_DOTS }, (_, i) => {
  const angle = (i / RING_DOTS) * Math.PI * 2 - Math.PI / 2;
  return {
    x: CENTER.x + Math.cos(angle) * RADIUS,
    y: CENTER.y + Math.sin(angle) * RADIUS * 0.82,
  };
});

/** The two shared attributes every ring account funnels through. */
export const hubs = [
  { x: CENTER.x - 74, y: CENTER.y, type: "instrument" as const, label: "shared card" },
  { x: CENTER.x + 74, y: CENTER.y, type: "device" as const, label: "shared device" },
];

/** Every account connects to both hubs — that convergence is the signal. */
export const ringEdges = ringPositions.flatMap((p, i) =>
  hubs.map((h, hi) => ({ id: `e-${i}-${hi}`, x1: p.x, y1: p.y, x2: h.x, y2: h.y })),
);

const RingGraph = forwardRef<SVGSVGElement>(function RingGraph(_props, ref) {
  return (
    <svg
      ref={ref}
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      style={{ width: "100%", height: "auto", overflow: "visible" }}
      aria-hidden="true"
    >
      <defs>
        <radialGradient id="rs-hub-glow">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Edges first so nodes sit on top. Drawn with stroke-dashoffset so they
          can be "written in" rather than faded, which reads as a connection
          being discovered. */}
      <g className="rs-edges">
        {ringEdges.map((e) => (
          <line
            key={e.id}
            className="rs-edge rs-anim"
            x1={e.x1}
            y1={e.y1}
            x2={e.x2}
            y2={e.y2}
            stroke="var(--accent)"
            strokeWidth="1.1"
            strokeOpacity="0.5"
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset="1"
          />
        ))}
      </g>

      {/* Hub glows */}
      <g className="rs-hub-glows">
        {hubs.map((h, i) => (
          <circle
            key={`glow-${i}`}
            className="rs-hub-glow rs-anim"
            cx={h.x}
            cy={h.y}
            r="70"
            fill="url(#rs-hub-glow)"
            opacity="0"
          />
        ))}
      </g>

      {/* The shared attributes */}
      <g className="rs-hubs">
        {hubs.map((h, i) => (
          <g key={`hub-${i}`} className="rs-hub rs-anim" opacity="0">
            <rect
              x={h.x - 11}
              y={h.y - 11}
              width="22"
              height="22"
              rx="5"
              fill={NODE_COLORS[h.type]}
              transform={`rotate(45 ${h.x} ${h.y})`}
            />
            <text
              x={h.x}
              y={h.y + (i === 0 ? -34 : 44)}
              textAnchor="middle"
              fill="var(--text-muted)"
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                letterSpacing: "0.08em",
              }}
            >
              {h.label}
            </text>
          </g>
        ))}
      </g>

      {/* The eighteen transactions. Index < RING_DOTS become the ring. */}
      <g className="rs-dots">
        {gridPositions.map((p, i) => (
          <circle
            key={`dot-${i}`}
            className={`rs-dot rs-anim ${i < RING_DOTS ? "rs-dot-ring" : "rs-dot-noise"}`}
            data-index={i}
            cx={p.x}
            cy={p.y}
            r={i < RING_DOTS ? 8 : 6}
            fill={i < RING_DOTS ? NODE_COLORS.customer : "var(--text-faint)"}
            fillOpacity={i < RING_DOTS ? 0.9 : 0.5}
          />
        ))}
      </g>
    </svg>
  );
});

export default RingGraph;
