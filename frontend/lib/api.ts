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

/**
 * "How close was this?" — a sensitivity read on the score that already exists,
 * not a second model. Only answerable because the score is a sum of named
 * signals, which is the argument for not using an LLM to produce it.
 */
export interface Counterfactual {
  current_score: number;
  nearest_boundary: number;
  boundary_name: string;
  gap: number;
  reading: string;
  note: string;
  smallest_change: {
    change: string;
    attribute_type: string;
    external_ref: string;
    accounts_now: number;
    score_would_become: number;
    delta: number;
    would_cross: boolean;
  } | null;
}

/** Mirrors CorpusShape in components/landing/TransactionField. */
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
  counterfactual: Counterfactual | null;
}

/**
 * The self-contained bundle for a cluster: evidence, Claude's explanation, the
 * human's decision, the audit rows, and a verification of the hash chain those
 * rows sit in.
 *
 * `integrity.chain_intact` is the real guarantee. `bundle_digest` is a
 * CHECKSUM, not a signature — it detects corruption in transit and proves
 * nothing about origin, because there is no key. The UI must not call it
 * signed.
 */
export interface EvidencePack {
  generated_at: string;
  cluster: {
    id: string;
    status: string;
    score: number;
    cadence: string;
    detector_version: string;
    flagged_at: string;
  };
  explanation: { model: string; cost_usd: number; authority: string } | null;
  decision: { action: string | null; note: string };
  integrity: {
    chain_intact: boolean;
    rows_verified: number;
    summary: string;
    how_it_works: string;
  };
  guarantees: string[];
  bundle_digest: { algorithm: string; value: string; covers: string; note: string };
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

export interface HeldOutMetrics {
  split: string;
  run_at: string;
  detector_version: string;
  score_threshold: number;
  confident_threshold: number;
  source: string;
  headline: {
    precision: number;
    precision_unit: string;
    recall: number;
    recall_unit: string;
    false_positive_cost_inr: number;
  };
  confusion: {
    true_positives_clusters: number;
    false_positives_clusters: number;
    false_negatives_rings: number;
    rings_total: number;
    rings_detected: number;
    clusters_flagged: number;
    match_rule: string;
  };
  needs_review: {
    count: number;
    band: [number, number];
    note: string;
    clusters: {
      score: number;
      size: number;
      cadence: string;
      headline: string;
      reason: string;
    }[];
  };
  cost: {
    certain_review_cost_inr: number;
    contingent_trust_cost_inr: number;
    total_inr: number;
    review_cost_per_fp_inr: number;
    note: string;
  };
  cost_model: {
    assumptions: Record<string, unknown>;
    derived: Record<string, number>;
  };
  live_review_state: {
    queue: Record<string, number>;
    approved_false_positives: number;
    contingent_trust_cost_inr: number;
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

  /** Fetched on demand, not with the detail — it verifies the whole chain. */
  evidencePack: (id: string) => get<EvidencePack>(`/clusters/${id}/evidence-pack`),

  /** Corpus shape for the landing field. No labels leave this endpoint. */
  corpus: () => get<CorpusShape>("/eval/corpus"),

  scorecard: () => get<Scorecard>("/eval/scorecard"),

  /** Held-out evaluation numbers. Defaults to the stored snapshot. */
  metrics: (split = "holdout") =>
    get<HeldOutMetrics>(`/metrics?split=${split}`),

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
