import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { cohortLabel, inr, relTime } from "@/lib/format";
import { ArrowLeft } from "lucide-react";
import { ErrorState } from "@/components/ErrorState";
import { DecisionExplain } from "@/components/DecisionExplain";

export const dynamic = "force-dynamic";

export default async function RecoveryDetailPage({ params }: { params: { id: string } }) {
  try {
    const r = await api.recovery(Number(params.id));
    return (
      <AppShell>
        <Link href="/recoveries" className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-text">
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>

        <div className="mb-6 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold">Recovery #{r.id}</h1>
              <StatusBadge status={r.status} />
            </div>
            <div className="mt-1 text-xs text-muted">
              {r.payment_id ?? "—"} · created {relTime(r.created_at)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-muted">Amount</div>
            <div className="money text-2xl font-semibold">{inr(r.amount_paise)}</div>
            {r.recovered_paise > 0 && (
              <div className="money mt-1 text-sm text-good">Recovered {inr(r.recovered_paise)}</div>
            )}
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Info label="Cohort" value={cohortLabel(r.cohort)} />
          <Info label="Attempts" value={String(r.attempts)} />
          <Info label="Error" value={r.error_code ?? "—"} />
        </div>

        {r.error_description && (
          <div className="mt-4 card p-4">
            <div className="text-xs uppercase tracking-wider text-muted">Original error</div>
            <div className="mt-1 text-sm">{r.error_description}</div>
          </div>
        )}

        {r.decision_context && (
          <div className="mt-4">
            <DecisionExplain ctx={r.decision_context} />
          </div>
        )}

        {r.strategy && (
          <div className="mt-4 card p-4">
            <div className="text-xs uppercase tracking-wider text-muted">Strategy chosen</div>
            <pre className="mt-2 overflow-x-auto rounded-md bg-black/40 p-3 text-xs">
              {JSON.stringify(r.strategy, null, 2)}
            </pre>
          </div>
        )}

        <div className="mt-6">
          <div className="mb-2 text-sm font-medium">Audit trail</div>
          <div className="card divide-y divide-border">
            {r.audit.length === 0 && (
              <div className="p-6 text-sm text-muted">No audit entries yet.</div>
            )}
            {r.audit.map((a, i) => (
              <div key={i} className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="pill">{a.actor}</span>
                    <span className="text-sm font-medium">{a.step}</span>
                  </div>
                  <div className="text-xs text-muted">{relTime(a.at)}</div>
                </div>
                <pre className="mt-2 overflow-x-auto rounded-md bg-black/30 p-3 text-xs text-muted">
                  {JSON.stringify(a.detail, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </div>
      </AppShell>
    );
  } catch {
    return <AppShell><ErrorState message="Recovery not found or backend not reachable." /></AppShell>;
  }
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 text-sm">{value}</div>
    </div>
  );
}
