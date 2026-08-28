"use client";

/**
 * The cluster's entity graph as a node-link diagram.
 *
 * A hand-rolled force layout rather than a library. It is ~40 lines, has no
 * dependency, and — importantly — runs to convergence once on mount instead of
 * animating on a RAF loop forever. A console tab left open should not hold a
 * CPU core; a settled diagram is also easier to read and to point at during a
 * review.
 *
 * Three forces: repulsion between every pair, a spring along each edge, and a
 * weak pull toward centre so disconnected pieces do not drift off-canvas. Seeded
 * from a deterministic circle, so the same cluster always lays out the same way.
 */

import { useMemo } from "react";
import type { GraphEdge, GraphNode } from "@/lib/api";
import { NODE_COLORS } from "@/lib/tokens";

const W = 640;
const H = 420;
const ITERATIONS = 320;

interface Placed {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  node: GraphNode;
  degree: number;
}

function layout(nodes: GraphNode[], edges: GraphEdge[]): Placed[] {
  const degree = new Map<string, number>();
  edges.forEach((e) => {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  });

  // Deterministic seeding: attributes near the middle, accounts on a ring.
  const placed: Placed[] = nodes.map((n, i) => {
    const isAttribute = n.type !== "customer";
    const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2;
    const radius = isAttribute ? 40 : 150;
    return {
      id: n.id,
      x: W / 2 + Math.cos(angle) * radius,
      y: H / 2 + Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
      node: n,
      degree: degree.get(n.id) ?? 0,
    };
  });

  const byId = new Map(placed.map((p) => [p.id, p]));
  const links = edges
    .map((e) => ({ a: byId.get(e.source), b: byId.get(e.target), w: e.weight }))
    .filter((l): l is { a: Placed; b: Placed; w: number } => !!l.a && !!l.b);

  for (let step = 0; step < ITERATIONS; step++) {
    // Cooling: large moves early, fine adjustment late.
    const alpha = 1 - step / ITERATIONS;

    // Repulsion.
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i];
        const b = placed[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.01) {
          dx = (i - j) * 0.5;
          dy = 0.5;
          dist = 0.5;
        }
        const force = (2600 / (dist * dist)) * alpha;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx -= fx;
        a.vy -= fy;
        b.vx += fx;
        b.vy += fy;
      }
    }

    // Springs. Heavier edges pull a little tighter, so a card used fifty times
    // sits visibly closer than one used twice.
    links.forEach(({ a, b, w }) => {
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(0.01, Math.hypot(dx, dy));
      const target = 96 - Math.min(28, Math.log2(w + 1) * 7);
      const force = (dist - target) * 0.055 * alpha;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    });

    // Centring plus damping.
    placed.forEach((p) => {
      p.vx += (W / 2 - p.x) * 0.012 * alpha;
      p.vy += (H / 2 - p.y) * 0.012 * alpha;
      p.vx *= 0.82;
      p.vy *= 0.82;
      p.x = Math.max(30, Math.min(W - 30, p.x + p.vx));
      p.y = Math.max(30, Math.min(H - 30, p.y + p.vy));
    });
  }

  return placed;
}

export default function GraphView({
  nodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
}) {
  const placed = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const byId = useMemo(() => new Map(placed.map((p) => [p.id, p])), [placed]);

  if (!nodes.length) {
    return (
      <div style={{ color: "var(--text-faint)", padding: "2rem", textAlign: "center" }}>
        No graph data for this cluster.
      </div>
    );
  }

  const maxWeight = Math.max(1, ...edges.map((e) => e.weight));

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
        <g>
          {edges.map((e, i) => {
            const a = byId.get(e.source);
            const b = byId.get(e.target);
            if (!a || !b) return null;
            return (
              <line
                key={`${e.source}-${e.target}-${i}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="var(--accent)"
                strokeOpacity={0.18 + (e.weight / maxWeight) * 0.45}
                strokeWidth={0.8 + (e.weight / maxWeight) * 2.4}
              >
                <title>
                  {e.link_type.replace("shared_", "shared ")} · {e.weight} transactions
                </title>
              </line>
            );
          })}
        </g>

        <g>
          {placed.map((p) => {
            const isAccount = p.node.type === "customer";
            const r = isAccount ? 9 : 7 + Math.min(6, p.degree);
            return (
              <g key={p.id}>
                {isAccount ? (
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={r}
                    fill={NODE_COLORS.customer}
                    fillOpacity={0.9}
                    stroke="var(--ink)"
                    strokeWidth={2}
                  />
                ) : (
                  <rect
                    x={p.x - r}
                    y={p.y - r}
                    width={r * 2}
                    height={r * 2}
                    rx={3}
                    fill={NODE_COLORS[p.node.type]}
                    fillOpacity={0.92}
                    stroke="var(--ink)"
                    strokeWidth={2}
                    transform={`rotate(45 ${p.x} ${p.y})`}
                  />
                )}
                <title>
                  {p.node.type} · {p.node.external_ref} · {p.degree} link(s)
                </title>
              </g>
            );
          })}
        </g>
      </svg>

      <div
        style={{
          display: "flex",
          gap: "1.1rem",
          flexWrap: "wrap",
          marginTop: "0.75rem",
          paddingTop: "0.75rem",
          borderTop: "1px solid var(--line)",
        }}
      >
        {(
          [
            ["customer", "account"],
            ["instrument", "card / bank"],
            ["device", "device"],
            ["address", "address"],
          ] as const
        ).map(([type, label]) => (
          <span
            key={type}
            className="rs-mono"
            style={{ display: "flex", alignItems: "center", gap: "0.4rem", color: "var(--text-faint)" }}
          >
            <span
              style={{
                width: 9,
                height: 9,
                background: NODE_COLORS[type],
                borderRadius: type === "customer" ? "50%" : 2,
                transform: type === "customer" ? "none" : "rotate(45deg)",
                display: "inline-block",
              }}
            />
            {label}
          </span>
        ))}
        <span className="rs-mono" style={{ color: "var(--text-faint)", marginLeft: "auto" }}>
          thicker edge = more shared transactions
        </span>
      </div>
    </div>
  );
}
