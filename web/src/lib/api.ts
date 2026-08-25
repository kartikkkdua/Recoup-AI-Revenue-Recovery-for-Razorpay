const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export type Summary = {
  window_hours: number;
  total_amount_paise: number;
  recovered_amount_paise: number;
  recovery_rate: number;
  precision: number;
  gateway_fees_paise: number;
  attempts_total: number;
  counts: { total: number; recovered: number; lost: number; skipped: number };
};

export type ModeSummary = Summary & { mode: "agent" | "naive" };

export type Compare = {
  window_hours: number;
  agent: ModeSummary;
  naive: ModeSummary;
  lift: {
    extra_recovered_paise: number;
    fees_saved_paise: number;
    attempts_saved: number;
    recovery_rate_delta: number;
  };
};

export type CohortRow = {
  cohort: string; count: number; amount_paise: number;
  recovered_paise: number; recovery_rate: number; gateway_fees_paise?: number;
};

export type RecoveryListItem = {
  id: number; payment_id: string | null; order_id: string | null;
  amount_paise: number; recovered_paise: number; currency: string;
  cohort: string; status: string; attempts: number; created_at: string;
  error_code: string | null; error_description: string | null;
};

export type AuditEntry = { step: string; actor: string; detail: Record<string, unknown>; at: string };

export type DecisionContext = {
  classification: { cohort: string; confidence: number; reasoning: string } | null;
  probability: {
    prior?: number; learned_blended?: number;
    observed_attempts?: number; observed_p?: number;
  } | null;
  gate_triggered: { step: string; [k: string]: unknown } | null;
  strategy_reason: string | null;
};

export type RecoveryDetail = RecoveryListItem & {
  subscription_id: string | null; customer_id: string | null;
  strategy: Record<string, unknown> | null;
  strategy_mode: "agent" | "naive";
  gateway_fee_paise: number;
  decision_context: DecisionContext;
  updated_at: string; audit: AuditEntry[];
};

export type Reliability = {
  duplicates_dropped_total: number;
  rate_limiter: { max_per_customer_per_24h: number; customers_tracked: number; denials_total: number };
  razorpay_circuit: { state: "closed" | "open" | "half_open"; consecutive_failures: number; opens_remaining_s: number };
};

export type LearnedRow = {
  cohort: string; action: string; hour_ist: number;
  attempted: number; succeeded: number; observed_p: number;
};

export const api = {
  summary: (hours = 24 * 30) => req<Summary>(`/api/metrics/summary?hours=${hours}`),
  compare: (hours = 24 * 30) => req<Compare>(`/api/metrics/compare?hours=${hours}`),
  cohorts: (hours = 24 * 30, mode: "agent" | "naive" = "agent") =>
    req<{ mode: string; cohorts: CohortRow[] }>(`/api/metrics/cohorts?hours=${hours}&mode=${mode}`),
  recoveries: (params: { limit?: number; offset?: number; status?: string; cohort?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.limit) q.set("limit", String(params.limit));
    if (params.offset) q.set("offset", String(params.offset));
    if (params.status) q.set("status", params.status);
    if (params.cohort) q.set("cohort", params.cohort);
    return req<{ items: RecoveryListItem[] }>(`/api/recoveries?${q}`);
  },
  recovery: (id: number) => req<RecoveryDetail>(`/api/recoveries/${id}`),
  rules: () => req<{ items: RuleRow[] }>(`/api/rules`),
  updateRule: (cohort: string, body: RuleOverride) =>
    req<{ ok: boolean }>(`/api/rules/${cohort}`, { method: "PUT", body: JSON.stringify({ cohort, ...body }) }),
  resetRule: (cohort: string) =>
    req<{ ok: boolean }>(`/api/rules/${cohort}`, { method: "DELETE" }),
  runSimulator: (count: number, mode: "agent" | "naive" = "agent") =>
    req<{ injected: number; mode: string }>(`/api/simulator/run`, {
      method: "POST",
      body: JSON.stringify({ count, mode }),
    }),
  runBenchmark: (count: number) =>
    req<{ injected_per_mode: number; total_injected: number }>(`/api/simulator/benchmark`, {
      method: "POST",
      body: JSON.stringify({ count }),
    }),
  reliability: () => req<Reliability>(`/api/metrics/reliability`),
  learned: () => req<{ rows: LearnedRow[] }>(`/api/metrics/learned`),
  roiDefaults: () => req<RoiDefaults>(`/api/roi/defaults`),
  roiEstimate: (input: RoiInput) =>
    req<RoiEstimate>(`/api/roi/estimate`, { method: "POST", body: JSON.stringify(input) }),
  subscriptionSummary: (hours = 24 * 30) => req<SubscriptionSummary>(`/api/subscriptions/summary?hours=${hours}`),
  subscriptionList: (limit = 50) => req<{ items: SubscriptionRow[] }>(`/api/subscriptions?limit=${limit}`),
  driftAlerts: () => req<{ alerts: DriftAlert[] }>(`/api/metrics/drift`),
};

export type SubscriptionSummary = {
  window_hours: number;
  counts: { total: number; recovered: number; churned: number; in_flight: number };
  mrr_at_risk_paise: number;
  mrr_retained_paise: number;
  retention_rate: number;
  annualised_mrr_retained_paise: number;
};

export type SubscriptionRow = {
  id: number;
  subscription_id: string;
  payment_id: string | null;
  amount_paise: number;
  recovered_paise: number;
  cohort: string;
  status: string;
  attempts: number;
  created_at: string;
};

export type DriftAlert = {
  cohort: string;
  baseline_share: number;
  recent_share: number;
  delta_pp: number;
  severity: "info" | "warn" | "critical";
  recent_count: number;
};

export type RuleOverride = {
  max_attempts: number;
  backoff_seconds: number[];
  preferred_rails: string[];
  dunning_channels: string[];
  enabled: boolean;
};

export type RuleRow = {
  cohort: string;
  default: {
    action: string;
    max_attempts: number;
    backoff_seconds: number[];
    rails: string[];
    dunning_channels: string[];
    reason: string;
  } | null;
  override: RuleOverride | null;
};

export type RoiInput = {
  monthly_failed_txns: number;
  avg_ticket_rupees: number;
  subscription_share_pct: number;
};

export type RoiMixRow = {
  cohort: string; share: number;
  agent_recovery_rate: number; naive_recovery_rate: number;
  sourced_from: "observed" | "seed";
};

export type RoiDefaults = {
  mix: RoiMixRow[];
  fees: { attempt_paise: number; link_paise: number };
};

export type RoiEstimate = {
  monthly: {
    eligible_paise: number;
    agent_recovered_paise: number;
    naive_recovered_paise: number;
    lift_paise: number;
    fees_agent_paise: number;
    fees_naive_paise: number;
    fees_saved_paise: number;
  };
  annual: {
    eligible_paise: number;
    agent_recovered_paise: number;
    lift_paise: number;
    fees_saved_paise: number;
  };
  rates: { agent_weighted: number; naive_weighted: number; sub_ltv_bonus_multiplier: number };
  mix_used: RoiMixRow[];
};
