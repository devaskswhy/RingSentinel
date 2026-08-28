"use client";

/** Small shared console primitives: pills, metric tiles, section headers. */

import type { Cadence, ClusterStatus, SuggestedAction } from "@/lib/api";
import { CADENCE_COLORS, STATUS_COLORS } from "@/lib/tokens";

const CADENCE_LABEL: Record<Cadence, string> = {
  agent_like: "agent-like",
  human_like: "human-like",
  inconclusive: "inconclusive",
};

export function CadencePill({ cadence }: { cadence: Cadence }) {
  const c = CADENCE_COLORS[cadence];
  return (
    <span
      className="rs-pill"
      style={{ color: c.fg, background: c.bg, borderColor: c.border }}
      title={
        cadence === "agent_like"
          ? "Inter-transaction gaps are regular and faster than human reaction time"
          : cadence === "human_like"
            ? "Irregular or unhurried gaps, consistent with people acting manually"
            : "Timing was too ambiguous to classify"
      }
    >
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: "50%",
          background: "currentColor",
          display: "inline-block",
        }}
      />
      {CADENCE_LABEL[cadence]}
    </span>
  );
}

export function StatusPill({ status }: { status: ClusterStatus }) {
  const c = STATUS_COLORS[status];
  const label = status === "cleared" ? "approved" : status.replace("_", " ");
  return (
    <span className="rs-pill" style={{ color: c.fg, background: c.bg }}>
      {label}
    </span>
  );
}

const ACTION_LABEL: Record<SuggestedAction, string> = {
  likely_ring: "likely ring",
  review_closer: "look closer",
  likely_false_positive: "likely FP",
};

export function ActionPill({ action }: { action: SuggestedAction }) {
  const color =
    action === "likely_ring"
      ? "#fca5a5"
      : action === "likely_false_positive"
        ? "#86efac"
        : "#fcd34d";
  return (
    <span
      className="rs-pill"
      style={{ color, background: "rgba(255,255,255,0.04)" }}
      title="Claude's recommendation. Advisory only — it is never acted on automatically."
    >
      {ACTION_LABEL[action]}
    </span>
  );
}

export function ScoreBar({ score }: { score: number }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}>
      <span
        className="rs-mono"
        style={{ minWidth: "3.2ch", color: "var(--text)", fontVariantNumeric: "tabular-nums" }}
      >
        {score.toFixed(3)}
      </span>
      <span
        style={{
          width: 54,
          height: 3,
          background: "var(--line-strong)",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <span
          className="rs-anim"
          style={{
            position: "absolute",
            inset: 0,
            background: "var(--accent)",
            transform: `scaleX(${Math.max(0, Math.min(1, score))})`,
            transformOrigin: "left center",
          }}
        />
      </span>
    </span>
  );
}

export function Metric({
  label,
  value,
  sub,
  tone = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "accent" | "warn";
}) {
  const color =
    tone === "accent" ? "var(--accent)" : tone === "warn" ? "#fcd34d" : "var(--text)";
  return (
    <div style={{ padding: "0.9rem 1rem", background: "var(--ink-panel)" }}>
      <div className="rs-label" style={{ marginBottom: "0.4rem" }}>
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: "var(--step-2)",
          color,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ color: "var(--text-faint)", fontSize: "0.72rem", marginTop: "0.3rem" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export function SectionTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "1rem",
        marginBottom: "0.85rem",
      }}
    >
      <span className="rs-label">{children}</span>
      {right}
    </div>
  );
}
