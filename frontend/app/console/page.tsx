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
import Scorecard from "@/components/console/Scorecard";
import { CadencePill, ScoreBar, StatusPill } from "@/components/console/Bits";

type SortKey = "score" | "size" | "status" | "cadence";

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
  const [detail, setDetail] = useState<Detail | null>(null);
  const [filter, setFilter] = useState<ClusterStatus | "all">("all");
  const [sort, setSort] = useState<SortKey>("score");
  const [asc, setAsc] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const tableRef = useRef<HTMLTableSectionElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [list, card] = await Promise.all([api.listClusters(), api.scorecard()]);
      setClusters(list);
      setScorecard(card);
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

  const loadDetail = useCallback(async (id: string) => {
    try {
      setDetail(await api.getCluster(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (selected) loadDetail(selected);
  }, [selected, loadDetail]);

  // Row entrance. Transform and opacity only.
  useEffect(() => {
    if (!tableRef.current || loading) return;
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
        <button onClick={() => refresh()} style={refreshButton} className="rs-focus">
          Refresh
        </button>
      </header>

      {error && (
        <div
          style={{
            padding: "0.7rem 1.5rem",
            background: "rgba(239,68,68,0.1)",
            color: "#fca5a5",
            fontSize: "var(--step--1)",
            borderBottom: "1px solid rgba(239,68,68,0.25)",
          }}
        >
          {error} — is the API running at {process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}?
        </div>
      )}

      <div style={{ padding: "1.5rem", borderBottom: "1px solid var(--line)" }}>
        <Scorecard data={scorecard} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.05fr) minmax(0, 1fr)", flex: 1 }}>
        {/* ---- queue --------------------------------------------------- */}
        <div style={{ borderRight: "1px solid var(--line)", padding: "1.25rem 1.5rem" }}>
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
            </span>
          </div>

          {loading ? (
            <div className="rs-mono" style={{ color: "var(--text-faint)" }}>
              loading queue…
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--step--1)" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--line-strong)" }}>
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
                    onClick={() => setSelected(c.id)}
                    style={{
                      borderBottom: "1px solid var(--line)",
                      cursor: "pointer",
                      background: selected === c.id ? "var(--ink-hover)" : "transparent",
                      transition: "background var(--dur-fast) var(--ease)",
                    }}
                  >
                    <td style={tdStyle}>
                      <ScoreBar score={c.score} />
                    </td>
                    <td style={{ ...tdStyle, fontVariantNumeric: "tabular-nums" }}>{c.size}</td>
                    <td style={tdStyle}>
                      <CadencePill cadence={c.cadence} />
                    </td>
                    <td style={tdStyle}>
                      <StatusPill status={c.status} />
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
        </div>

        {/* ---- detail -------------------------------------------------- */}
        <div style={{ padding: "1.25rem 1.5rem", minWidth: 0 }}>
          {detail ? (
            <ClusterDetail
              detail={detail}
              onReviewed={onReviewed}
              onGenerated={() => selected && loadDetail(selected)}
            />
          ) : (
            <div className="rs-mono" style={{ color: "var(--text-faint)" }}>
              select a cluster
            </div>
          )}
        </div>
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
  padding: "0.5rem 0.6rem 0.5rem 0",
  fontFamily: "var(--font-mono)",
  fontSize: "0.7rem",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--text-faint)",
  fontWeight: 400,
  cursor: "pointer",
  userSelect: "none",
};

const tdStyle: React.CSSProperties = {
  padding: "0.6rem 0.6rem 0.6rem 0",
  verticalAlign: "middle",
};

const filterButton: React.CSSProperties = {
  padding: "0.3rem 0.75rem",
  border: "1px solid",
  fontSize: "0.72rem",
  fontFamily: "var(--font-mono)",
  cursor: "pointer",
  transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
};

const refreshButton: React.CSSProperties = {
  padding: "0.35rem 0.8rem",
  background: "transparent",
  border: "1px solid var(--line-strong)",
  color: "var(--text-muted)",
  fontSize: "0.72rem",
  fontFamily: "var(--font-mono)",
  cursor: "pointer",
};
