"use client";

/**
 * The audit trail, newest first.
 *
 * Styled to look like what it is: an append-only ledger. Every row carries its
 * actor, because "who decided this" is the question the log exists to answer.
 * Nothing here is editable — the table itself rejects UPDATE and DELETE at the
 * database level, and the UI should not imply otherwise.
 */

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import type { AuditEntry } from "@/lib/api";
import { DURATION, EASE_OUT, STAGGER } from "@/lib/tokens";

/**
 * Actors on the luminance ramp, not on three hues.
 *
 * The human gets the accent because who decided is the fact this trail exists
 * to record — the detector flagging and Claude explaining are both automatic
 * and unremarkable by comparison. Ranking the actors by prominence says
 * something true; giving them each a colour said nothing.
 */
const ACTOR_COLOR: Record<AuditEntry["actor"], string> = {
  system: "var(--text-faint)",
  claude: "var(--text-muted)",
  human: "var(--accent)",
};

const ACTION_LABEL: Record<string, string> = {
  cluster_flagged: "flagged for review",
  case_file_generated: "case file written",
  cluster_approved: "approved by human",
  cluster_dismissed: "dismissed by human",
  ingest_transaction: "transaction ingested",
  detection_run: "detection run",
};

function summarise(entry: AuditEntry): string {
  const d = entry.detail as Record<string, unknown>;
  switch (entry.action) {
    case "cluster_flagged":
      return `score ${Number(d.score ?? 0).toFixed(3)} · ${d.size} accounts · ${d.cadence}`;
    case "case_file_generated":
      return `recommends "${d.suggested_action}" · ${d.model}`;
    case "cluster_approved":
    case "cluster_dismissed":
      return `${d.reviewer ?? "unknown"} — ${String(d.reason ?? "").slice(0, 120)}`;
    default:
      return "";
  }
}

export default function AuditTrail({ entries }: { entries: AuditEntry[] }) {
  const root = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (!root.current) return;
    const ctx = gsap.context(() => {
      gsap.from(".rs-audit-row", {
        opacity: 0,
        x: -8,
        duration: DURATION.fast,
        ease: EASE_OUT,
        stagger: STAGGER,
      });
    }, root);
    return () => ctx.revert();
  }, [entries]);

  if (!entries.length) {
    return (
      <div className="rs-mono" style={{ color: "var(--text-faint)" }}>
        no events yet
      </div>
    );
  }

  const ordered = [...entries].reverse();

  return (
    <ol
      ref={root}
      style={{ listStyle: "none", margin: 0, padding: 0, borderLeft: "1px solid var(--line)" }}
    >
      {ordered.map((entry, i) => (
        <li
          key={`${entry.at}-${i}`}
          className="rs-audit-row rs-anim"
          style={{ position: "relative", padding: "0.7rem 0 0.7rem 1.1rem" }}
        >
          <span
            style={{
              position: "absolute",
              left: -3.5,
              top: "1.15rem",
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: ACTOR_COLOR[entry.actor],
            }}
          />
          <div style={{ display: "flex", gap: "0.6rem", alignItems: "baseline", flexWrap: "wrap" }}>
            <span
              className="rs-tag"
              style={{ color: ACTOR_COLOR[entry.actor] }}
            >
              {entry.actor}
            </span>
            <span style={{ fontSize: "var(--console-body)", color: "var(--text)" }}>
              {ACTION_LABEL[entry.action] ?? entry.action}
            </span>
            <span className="rs-mono" style={{ color: "var(--text-faint)", marginLeft: "auto" }}>
              {new Date(entry.at).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </span>
          </div>
          {summarise(entry) && (
            <div
              style={{
                color: "var(--text-muted)",
                fontSize: "var(--console-small)",
                marginTop: "0.25rem",
                lineHeight: 1.5,
              }}
            >
              {summarise(entry)}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
