"use client";

/**
 * Surface B — the review console.
 *
 * Scanned, not read. No loader, no pinning, no scroll-driven anything: a
 * reviewer opens this many times a day and wants the queue on screen
 * immediately. GSAP is here only for list entrances and panel swaps, and every
 * one of those animates transform and opacity alone — this view re-renders on
 * every decision, and touching geometry would cost a reflow each time.
 *
 * It shares the landing page's tokens, so the two feel like one product without
 * behaving like one.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { gsap } from "gsap";
import {
  api,
  type ClusterDetail as Detail,
  type ClusterStatus,
  type ClusterSummary,
  type Scorecard as ScorecardData,
} from "@/lib/api";
import { DURATION, EASE_OUT, STAGGER } from "@/lib/tokens";
import ClusterDetail from "@/components/console/ClusterDetail";
import Orientation from "@/components/console/Orientation";
import { prefersReducedMotion } from "@/lib/tokens";
import Scorecard from "@/components/console/Scorecard";
import { CadenceTag, ScoreBar, StatusTag } from "@/components/console/Bits";

type SortKey = "score" | "size" | "status" | "cadence";

/**
 * How often the console re-reads the backend.
 *
 * Polling, not WebSockets. The queue changes on the order of seconds, a
 * reviewer is not watching a tape, and a 4s GET against a local API costs
 * nothing. Pushing would be more machinery for no behaviour a human would
 * notice.
 */
const POLL_INTERVAL_MS = 4000;

const FILTERS: { label: string; value: ClusterStatus | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Pending", value: "pending" },
  { label: "Approved", value: "cleared" },
  { label: "Dismissed", value: "dismissed" },
];

export default function Console() {
  const [clusters, setClusters] = useState<ClusterSummary[]>([]);
  const [scorecard, setScorecard] = useState<ScorecardData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [filter, setFilter] = useState<ClusterStatus | "all">("all");
  const [sort, setSort] = useState<SortKey>("score");
  const [asc, setAsc] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const tableRef = useRef<HTMLTableSectionElement>(null);
  const [live, setLive] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [newCount, setNewCount] = useState(0);

  // Which clusters we have already animated in. Without this the entrance
  // animation re-fires on every poll and the whole table pulses every four
  // seconds - fine in dev, awful on camera.
  const animatedIds = useRef<string>("");
  const knownIds = useRef<Set<string>>(new Set());
  const loadDetailRef = useRef<((id: string) => Promise<void>) | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [list, card] = await Promise.all([api.listClusters(), api.scorecard()]);

      // Flag genuinely new clusters so a live arrival is visible rather than
      // silently appearing in a sorted list.
      if (knownIds.current.size) {
        const fresh = list.filter((c) => !knownIds.current.has(c.id));
        if (fresh.length) setNewCount((n) => n + fresh.length);
      }
      knownIds.current = new Set(list.map((c) => c.id));

      setClusters(list);
      setScorecard(card);
      setLastUpdate(new Date());
      setError(null);
      return list;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh().then((list) => {
      if (list.length && !selected) setSelected(list[0].id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll while `live`. Refreshing the detail pane alongside the list is safe:
  // the review form's state is local to ClusterDetail and keyed on cluster id,
  // so a re-fetch of the same cluster never clears a half-typed reason.
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => {
      refresh();
      if (selected) loadDetailRef.current?.(selected);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, selected, refresh]);

  const loadDetail = useCallback(async (id: string) => {
    try {
      setDetail(await api.getCluster(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    loadDetailRef.current = loadDetail;
  }, [loadDetail]);

  useEffect(() => {
    if (selected) loadDetail(selected);
  }, [selected, loadDetail]);

  // Row entrance. Transform and opacity only.
  useEffect(() => {
    if (!tableRef.current || loading) return;

    // Only animate when the SET of visible clusters actually changed. Polling
    // re-renders every few seconds; re-running the entrance each time would
    // make the table strobe.
    const signature = clusters.map((c) => c.id).join(",") + `|${filter}|${sort}|${asc}`;
    if (signature === animatedIds.current) return;
    animatedIds.current = signature;

    const ctx = gsap.context(() => {
      gsap.from(".rs-row", {
        opacity: 0,
        y: 6,
        duration: DURATION.fast,
        ease: EASE_OUT,
        stagger: STAGGER,
      });
    }, tableRef);
    return () => ctx.revert();
  }, [clusters, filter, sort, asc, loading]);

  const visible = useMemo(() => {
    const rows = clusters.filter((c) => filter === "all" || c.status === filter);
    const dir = asc ? 1 : -1;
    return [...rows].sort((a, b) => {
      switch (sort) {
        case "size":
          return (a.size - b.size) * dir;
        case "status":
          return a.status.localeCompare(b.status) * dir;
        case "cadence":
          return a.cadence.localeCompare(b.cadence) * dir;
        default:
          return (a.score - b.score) * dir;
      }
    });
  }, [clusters, filter, sort, asc]);

  // Walking the queue in order is the point of the stacked layout: open one,
  // read it, move to the next without going back up.
  const position = selected ? visible.findIndex((c) => c.id === selected) : -1;
  const prevId = position > 0 ? visible[position - 1].id : null;
  const nextId =
    position >= 0 && position < visible.length - 1 ? visible[position + 1].id : null;

  function step(delta: number) {
    const target = delta < 0 ? prevId : nextId;
    if (target) setSelected(target);
  }

  // Bring the case into view when one is opened. Without this the detail
  // renders below the fold and the click appears to do nothing at all.
  useEffect(() => {
    if (!selected || !detailRef.current) return;
    detailRef.current.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
  }, [selected]);


  const onReviewed = useCallback(async () => {
    await refresh();
    if (selected) await loadDetail(selected);
  }, [refresh, selected, loadDetail]);

  function toggleSort(key: SortKey) {
    if (sort === key) setAsc((v) => !v);
    else {
      setSort(key);
      setAsc(false);
    }
  }

  return (
    <div style={{ minHeight: "100svh", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.85rem 1.5rem",
          borderBottom: "1px solid var(--line)",
          position: "sticky",
          top: 0,
          background: "var(--ink)",
          zIndex: 10,
        }}
      >
        <Link
          href="/"
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 600,
            color: "var(--text)",
            textDecoration: "none",
            letterSpacing: "-0.02em",
          }}
        >
          Ring<span style={{ color: "var(--accent)" }}>Sentinel</span>
          <span className="rs-label" style={{ marginLeft: "0.85rem" }}>
            review console
          </span>
        </Link>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {newCount > 0 && (
            <button
              onClick={() => setNewCount(0)}
              className="rs-tag rs-focus"
              style={{
                color: "var(--ink)",
                background: "var(--accent)",
                border: "none",
                padding: "0.3em 0.6em",
                cursor: "pointer",
              }}
              title="Clusters that appeared since you started watching"
            >
              +{newCount} new
            </button>
          )}
          <button
            onClick={() => setLive((v) => !v)}
            className="rs-focus"
            style={{
              ...refreshButton,
              color: live ? "var(--accent)" : "var(--text-faint)",
              borderColor: live ? "var(--accent)" : "var(--line-strong)",
              display: "flex",
              alignItems: "center",
              gap: "0.45rem",
            }}
            title={
              live
                ? `Polling every ${POLL_INTERVAL_MS / 1000}s. Click to pause.`
                : "Paused. Click to resume live updates."
            }
          >
            <span
              className={live ? "rs-live-dot" : undefined}
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: live ? "var(--accent)" : "var(--text-faint)",
                display: "inline-block",
              }}
            />
            {live ? "live" : "paused"}
          </button>
          <button onClick={() => refresh()} style={refreshButton} className="rs-focus">
            Refresh
          </button>
        </div>
      </header>

      {error && (
        <div
          style={{
            padding: "0.7rem 1.5rem",
            background: "rgba(239,68,68,0.1)",
            color: "var(--danger)",
            fontSize: "var(--console-body)",
            borderBottom: "1px solid rgba(239,68,68,0.25)",
          }}
        >
          {error} — is the API running at {process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}?
        </div>
      )}

      <Orientation />

      <div style={{ padding: "1.5rem", borderBottom: "1px solid var(--line)" }}>
        <Scorecard data={scorecard} />
      </div>

      <div style={{ flex: 1 }}>
        {/* ---- queue, full width -------------------------------------- */}
        <div className="rs-console-shell" style={{ paddingBlock: "1.75rem 2.5rem" }}>
          <div
            style={{
              display: "flex",
              gap: "0.4rem",
              marginBottom: "1rem",
              flexWrap: "wrap",
            }}
          >
            {FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setFilter(f.value)}
                className="rs-focus"
                style={{
                  ...filterButton,
                  color: filter === f.value ? "var(--ink)" : "var(--text-muted)",
                  background: filter === f.value ? "var(--accent)" : "transparent",
                  borderColor: filter === f.value ? "var(--accent)" : "var(--line-strong)",
                }}
              >
                {f.label}
              </button>
            ))}
            <span
              className="rs-mono"
              style={{ marginLeft: "auto", color: "var(--text-faint)", alignSelf: "center" }}
            >
              {visible.length} cluster{visible.length === 1 ? "" : "s"}
              {lastUpdate && (
                <span style={{ marginLeft: "0.6rem" }}>
                  · updated {lastUpdate.toLocaleTimeString()}
                </span>
              )}
            </span>
          </div>

          {loading ? (
            <div className="rs-mono" style={{ color: "var(--text-faint)" }}>
              loading queue…
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--console-body)" }}
              className="rs-anim">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--line-strong)" }}>
                  <th style={{ ...thStyle, cursor: "default" }}>id</th>
                  <Th onClick={() => toggleSort("score")} active={sort === "score"} asc={asc}>
                    score
                  </Th>
                  <Th onClick={() => toggleSort("size")} active={sort === "size"} asc={asc}>
                    accts
                  </Th>
                  <Th onClick={() => toggleSort("cadence")} active={sort === "cadence"} asc={asc}>
                    cadence
                  </Th>
                  <Th onClick={() => toggleSort("status")} active={sort === "status"} asc={asc}>
                    status
                  </Th>
                  <th style={{ ...thStyle, cursor: "default" }}>evidence</th>
                </tr>
              </thead>
              <tbody ref={tableRef}>
                {visible.map((c) => (
                  <tr
                    key={c.id}
                    className="rs-row rs-anim"
                    data-selected={selected === c.id}
                    onClick={() => setSelected(c.id)}
                  >
                    <td
                      className="rs-row-id rs-mono"
                      style={{
                        ...tdStyle,
                        paddingLeft: "0.7rem",
                        color: "var(--text-faint)",
                        letterSpacing: "0.02em",
                      }}
                      title={c.id}
                    >
                      {c.id.slice(0, 8)}
                    </td>
                    <td style={tdStyle}>
                      <ScoreBar score={c.score} />
                    </td>
                    <td style={{ ...tdStyle, fontVariantNumeric: "tabular-nums" }}>{c.size}</td>
                    <td style={tdStyle}>
                      <CadenceTag cadence={c.cadence} />
                    </td>
                    <td style={tdStyle}>
                      <StatusTag status={c.status} />
                    </td>
                    <td
                      style={{
                        ...tdStyle,
                        color: "var(--text-muted)",
                        maxWidth: 280,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={c.headline ?? ""}
                    >
                      {c.headline ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {!loading && !visible.length && (
            <div className="rs-mono" style={{ color: "var(--text-faint)", padding: "1.5rem 0" }}>
              nothing in this view. Run{" "}
              <code>docker compose exec backend python -m scripts.detect</code>
            </div>
          )}
          {!loading && visible.length > 0 && !selected && (
            <p className="rs-queue-hint">
              Select a cluster to open its full case below — the evidence, the
              signals behind the score, the graph, and the decision.
            </p>
          )}
        </div>

        {/* ---- detail, full width, scrolled into view ------------------ */}
        {detail && (
          <div ref={detailRef} className="rs-detail-stage">
            <div className="rs-console-shell">
              <div className="rs-detail-nav">
                <button onClick={() => step(-1)} disabled={!prevId} className="rs-focus rs-step-btn">
                  ← previous
                </button>
                <span className="rs-mono" style={{ color: "var(--text-faint)" }}>
                  cluster {position + 1} of {visible.length}
                </span>
                <button onClick={() => step(1)} disabled={!nextId} className="rs-focus rs-step-btn">
                  next →
                </button>
                <button
                  onClick={() => {
                    setSelected(null);
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }}
                  className="rs-focus rs-step-btn"
                  style={{ marginLeft: "auto" }}
                >
                  ↑ back to the queue
                </button>
              </div>

              <ClusterDetail
                detail={detail}
                onReviewed={onReviewed}
                onGenerated={() => selected && loadDetail(selected)}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Th({
  children,
  onClick,
  active,
  asc,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
  asc: boolean;
}) {
  return (
    <th
      onClick={onClick}
      style={{
        ...thStyle,
        color: active ? "var(--accent)" : "var(--text-faint)",
      }}
    >
      {children}
      {active && <span style={{ marginLeft: 4 }}>{asc ? "↑" : "↓"}</span>}
    </th>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "0.7rem 0.75rem 0.7rem 0",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--console-label)",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--text-faint)",
  fontWeight: 400,
  cursor: "pointer",
  userSelect: "none",
};

const tdStyle: React.CSSProperties = {
  padding: "0.8rem 0.75rem 0.8rem 0",
  verticalAlign: "middle",
  fontSize: "var(--console-body)",
};

const filterButton: React.CSSProperties = {
  padding: "0.3rem 0.75rem",
  border: "1px solid",
  fontSize: "var(--console-small)",
  fontFamily: "var(--font-mono)",
  cursor: "pointer",
  transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
};

const refreshButton: React.CSSProperties = {
  padding: "0.35rem 0.8rem",
  background: "transparent",
  border: "1px solid var(--line-strong)",
  color: "var(--text-muted)",
  fontSize: "var(--console-small)",
  fontFamily: "var(--font-mono)",
  cursor: "pointer",
};
