/**
 * Typed client for the RingSentinel backend.
 *
 * Shapes mirror the FastAPI responses from Phases 3 and 4. Kept in one file so
 * a backend change surfaces as a TypeScript error rather than an undefined at
 * runtime.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type Cadence = "agent_like" | "human_like" | "inconclusive";
export type ClusterStatus = "pending" | "cleared" | "dismissed" | "needs_review";
export type SuggestedAction =
  | "likely_ring"
  | "review_closer"
  | "likely_false_positive";

export interface ClusterSummary {
  id: string;
  status: ClusterStatus;
  score: number;
  cadence: Cadence;
  size: number;
  detector_version: string;
  has_case_file: boolean;
  suggested_action: SuggestedAction | null;
  headline: string | null;
}

export interface CaseFile {
  id: string;
  summary: string;
  confidence_note: string;
  suggested_action: SuggestedAction;
  key_signals: string[];
  caveats: string[];
  model: string;
  prompt_version: string;
  cluster_score_at_generation: number;
  detector_version: string;
  generated_at: string;
  stale: boolean;
  disclaimer: string;
}

export interface GraphNode {
  id: string;
  type: "customer" | "device" | "address" | "instrument";
  external_ref: string;
  first_seen_at: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  link_type: string;
  weight: number;
}

export interface SignalBreakdown {
  value: number;
  weight: number;
  weighted: number;
  explanation: string;
  shallow_accounts?: number;
}

export interface SharedAttribute {
  entity_id: string;
  attribute_type: string;
  external_ref: string;
  customer_count: number;
  observations: number;
  contribution: number;
}

export interface Evidence {
  score: number;
  size: number;
  headline: string;
  detector_version: string;
  signals: Record<string, SignalBreakdown>;
  shared_attributes: SharedAttribute[];
  cadence: {
    classification: Cadence;
    confidence: number;
    reason: string;
    median_gap_seconds: number;
    coefficient_of_variation: number;
  };
  timing: {
    cluster_median_gap_seconds: number;
    cluster_cv: number;
    baseline_median_gap_seconds: number;
    baseline_cv: number;
    accounts_measured: number;
  };
  notes: string[];
}

export interface AuditEntry {
  actor: "system" | "claude" | "human";
  action: string;
  detail: Record<string, unknown>;
  at: string;
}

export interface ClusterDetail {
  cluster: {
    id: string;
    status: ClusterStatus;
    score: number;
    cadence: Cadence;
    detector_version: string;
    created_at: string;
  };
  case_file: CaseFile | null;
  evidence: Evidence;
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
  audit_trail: AuditEntry[];
}

export interface Scorecard {
  scope: string;
  detector_benchmark: {
    available: boolean;
    note: string;
    rings_total: number;
    rings_detected: number;
    recall: number;
    clusters_flagged: number;
    true_positives: number;
    false_flags: number;
    precision: number;
    normal_accounts_total: number;
    normal_accounts_swept_in: number;
  };
  review_operations: {
    note: string;
    total: number;
    pending: number;
    approved: number;
    dismissed: number;
    needs_review: number;
    reviewed: number;
    reviewed_fraction: number;
  };
  false_positive_cost: {
    false_flags: number;
    dismissed_by_human: number;
    analyst_minutes_on_dismissed: number;
    minutes_per_review_assumed: number;
    dismissed_that_were_real_rings: number;
    note: string;
  };
  needs_more_data: {
    count: number;
    note: string;
    clusters: { cluster_id: string; score: number; reason: string }[];
  };
  claude_agreement: {
    decided: number;
    agreed: number;
    disagreed: number;
    rate: number | null;
    note: string;
  };
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      const parsed = JSON.parse(detail);
      detail = parsed.detail ?? detail;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    } catch {
      /* keep the raw body */
    }
    throw new Error(String(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  listClusters: (status?: ClusterStatus) =>
    get<ClusterSummary[]>(
      `/clusters${status ? `?status=${status}` : ""}`,
    ),

  getCluster: (id: string) => get<ClusterDetail>(`/clusters/${id}`),

  scorecard: () => get<Scorecard>("/eval/scorecard"),

  generateCaseFile: (id: string, force = false) =>
    post<{ created: boolean; reused_cache: boolean }>(
      `/clusters/${id}/case-file${force ? "?force=true" : ""}`,
    ),

  /** Both require a human-written reason — the backend rejects short ones. */
  approve: (id: string, reason: string, reviewer: string) =>
    post<{ status: string; note: string }>(`/clusters/${id}/approve`, {
      reason,
      reviewer,
    }),

  dismiss: (id: string, reason: string, reviewer: string) =>
    post<{ status: string; note: string }>(`/clusters/${id}/dismiss`, {
      reason,
      reviewer,
    }),
};
