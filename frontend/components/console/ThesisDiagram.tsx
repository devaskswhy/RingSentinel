"use client";

/**
 * The whole argument in one picture: the same transactions, twice.
 *
 * Left, scored one at a time — every one passes, because nothing about a single
 * transaction is wrong. Right, the same set as a graph — five of them run
 * through one card, and that convergence is the only thing that was ever
 * visible.
 *
 * Deliberately not a photograph or a stock illustration. The point is that this
 * is a view of data, and a picture of something else would undercut that. It is
 * also the same idea the landing page's field animates, drawn small and still,
 * so the two surfaces argue the same way.
 */

const LEFT = Array.from({ length: 12 }, (_, i) => ({
  x: 26 + (i % 4) * 34,
  y: 30 + Math.floor(i / 4) * 34,
}));

/** Five of the twelve converge on one shared card. */
const RING = [0, 3, 5, 8, 11];
const HUB = { x: 78, y: 64 };

export default function ThesisDiagram() {
  return (
    <svg
      viewBox="0 0 380 140"
      style={{ width: "100%", height: "auto", maxWidth: 460, display: "block" }}
      role="img"
      aria-label="The same twelve transactions, scored one at a time and then as a graph"
    >
      {/* ---------- left: one at a time ---------- */}
      <text x="0" y="12" className="rs-diagram-cap" fill="var(--text-faint)">
        SCORED ONE AT A TIME
      </text>
      {LEFT.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r="5" fill="var(--text-faint)" opacity="0.5" />
          <path
            d={`M${p.x - 2.4} ${p.y} l1.8 1.9 l3.2 -3.8`}
            stroke="var(--text-faint)"
            strokeWidth="1.3"
            fill="none"
            opacity="0.9"
          />
        </g>
      ))}
      <text x="0" y="134" className="rs-diagram-note" fill="var(--text-faint)">
        all approved
      </text>

      {/* ---------- divider ---------- */}
      <line x1="190" y1="16" x2="190" y2="128" stroke="var(--line)" strokeWidth="1" />

      {/* ---------- right: as a graph ---------- */}
      <g transform="translate(196, 0)">
        <text x="0" y="12" className="rs-diagram-cap" fill="var(--accent)">
          SEEN AS A GRAPH
        </text>

        {RING.map((i) => (
          <line
            key={`e${i}`}
            x1={LEFT[i].x}
            y1={LEFT[i].y}
            x2={HUB.x}
            y2={HUB.y}
            stroke="var(--accent)"
            strokeWidth="1"
            opacity="0.5"
          />
        ))}

        {LEFT.map((p, i) => {
          const inRing = RING.includes(i);
          return (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={inRing ? 5.5 : 5}
              fill={inRing ? "var(--accent)" : "var(--text-faint)"}
              opacity={inRing ? 1 : 0.22}
            />
          );
        })}

        {/* the shared attribute */}
        <rect
          x={HUB.x - 4.5}
          y={HUB.y - 4.5}
          width="9"
          height="9"
          fill="var(--accent)"
          transform={`rotate(45 ${HUB.x} ${HUB.y})`}
        />
        <text x="0" y="134" className="rs-diagram-note" fill="var(--accent)">
          five accounts, one card
        </text>
      </g>
    </svg>
  );
}
