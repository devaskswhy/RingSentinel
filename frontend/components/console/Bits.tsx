"use client";

/** Small shared console primitives: pills, metric tiles, section headers. */

import type { Cadence, ClusterStatus, SuggestedAction } from "@/lib/api";
import { ACTION_TAG, CADENCE_TAG, STATUS_TAG, TONE_COLOR, type Tone } from "@/lib/tokens";

/** One tag renderer. Every readout in the console goes through this. */
function Tag({ label, tone, title }: { label: string; tone: Tone; title?: string }) {
  return (
    <span className="rs-tag" data-tone={tone} style={{ color: TONE_COLOR[tone] }} title={title}>
      {label}
    </span>
  );
}

const CADENCE_TITLE: Record<Cadence, string> = {
  agent_like: "Inter-transaction gaps are regular and faster than human reaction time",
  human_like: "Irregular or unhurried gaps, consistent with people acting manually",
  inconclusive: "Timing was too ambiguous to classify",
};

export function CadenceTag({ cadence }: { cadence: Cadence }) {
  const t = CADENCE_TAG[cadence];
  return <Tag label={t.label} tone={t.tone} title={CADENCE_TITLE[cadence]} />;
}

const STATUS_TITLE: Record<ClusterStatus, string> = {
  pending: "Flagged, and the detector is confident. A human still has to decide.",
  needs_review: "Flagged, but inside the ambiguous band — the detector is unsure.",
  cleared: "A human confirmed this, with a written reason. No account was restricted.",
  dismissed: "A human judged this a false positive, with a written reason.",
};

export function StatusTag({ status }: { status: ClusterStatus }) {
  const t = STATUS_TAG[status];
  return <Tag label={t.label} tone={t.tone} title={STATUS_TITLE[status]} />;
}

export function ActionTag({ action }: { action: SuggestedAction }) {
  const t = ACTION_TAG[action];
  return (
    <Tag
      label={t.label}
      tone={t.tone}
      title="Claude's recommendation. Advisory only — it is never acted on automatically."
    />
  );
}

/** The two thresholds the detector actually uses (detection/config.py). */
const FLAG_THRESHOLD = 0.3;
const CONFIDENT_THRESHOLD = 0.45;

/**
 * Score readout with both thresholds marked on the track.
 *
 * The bar used to be a plain fill, which showed magnitude and nothing else — a
 * reviewer could see 0.42 was bigger than 0.37 but not that one of them sits
 * inside the ambiguous band. The ticks are the whole point: they turn a number
 * into a position relative to the decisions the system makes about it.
 */
export function ScoreBar({ score, width = 68 }: { score: number; width?: number }) {
  const clamped = Math.max(0, Math.min(1, score));
  const ambiguous = score < CONFIDENT_THRESHOLD;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.6rem" }}>
      <span
        className="rs-mono"
        style={{
          minWidth: "4ch",
          color: ambiguous ? "var(--signal)" : "var(--text)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {score.toFixed(3)}
      </span>
      <span
        style={{ width, height: 8, position: "relative", display: "inline-block" }}
        title={`Flag threshold ${FLAG_THRESHOLD}, confidence threshold ${CONFIDENT_THRESHOLD}`}
      >
        {/* track */}
        <span
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 3,
            height: 2,
            background: "var(--line-strong)",
          }}
        />
        {/* fill */}
        <span
          className="rs-anim"
          style={{
            position: "absolute",
            left: 0,
            top: 3,
            height: 2,
            width: "100%",
            background: ambiguous ? "var(--signal)" : "var(--accent)",
            transform: `scaleX(${clamped})`,
            transformOrigin: "left center",
          }}
        />
        {/* threshold ticks */}
        {[FLAG_THRESHOLD, CONFIDENT_THRESHOLD].map((t) => (
          <span
            key={t}
            style={{
              position: "absolute",
              left: `${t * 100}%`,
              top: 0,
              width: 1,
              height: 8,
              background: "var(--text-faint)",
            }}
          />
        ))}
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
    tone === "accent" ? "var(--accent)" : tone === "warn" ? "var(--signal)" : "var(--text)";
  return (
    <div style={{ padding: "0.9rem 1.1rem", background: "var(--ink-panel)" }}>
      <div className="rs-label" style={{ marginBottom: "0.5rem" }}>
        {label}
      </div>
      {/* Mono, not the display face. A measured quantity should look measured —
          the display face makes a number read as a marketing statistic. */}
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "var(--step-2)",
          fontWeight: 500,
          color,
          fontVariantNumeric: "tabular-nums",
          letterSpacing: "-0.02em",
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ color: "var(--text-faint)", fontSize: "0.72rem", marginTop: "0.35rem" }}>
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
