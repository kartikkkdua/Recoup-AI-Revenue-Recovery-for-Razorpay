import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { cohortLabel, pct } from "@/lib/format";
import { ErrorState } from "@/components/ErrorState";
import { FlaskConical, CheckCircle2, MinusCircle } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function ImpactPage() {
  try {
    const [ate, cate] = await Promise.all([api.ate(), api.cate()]);
    return (
      <AppShell>
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Causal impact</h1>
          <p className="text-sm text-muted">
            Variance-reduced ATE (stratified over cohort × ticket bucket) and per-slice CATE with 95% confidence intervals.
            This is the statistically-defensible version of the dashboard's raw agent-vs-naive comparison.
          </p>
        </div>

        {!ate.available ? (
          <div className="card p-8 text-center text-sm text-muted">
            No data in window. Run the benchmark from the dashboard to populate both agent and naive arms.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Metric label="ATE (stratified)" value={pct(ate.ate_stratified ?? 0)}
                      sub={`95% CI [${pct(ate.ci_low ?? 0)}, ${pct(ate.ci_high ?? 0)}]`} accent />
              <Metric label="Raw ATE" value={pct(ate.ate_raw ?? 0)}
                      sub={`agent ${pct(ate.p_agent ?? 0)} · naive ${pct(ate.p_naive ?? 0)}`} />
              <Metric label="Lift multiple" value={`${(ate.lift_multiple ?? 0).toFixed(2)}×`}
                      sub={`p_agent / p_naive`} />
              <Metric label="Slices used" value={String(ate.slices_used ?? 0)}
                      sub={`each with ≥5 samples per arm`} />
            </div>

            <div className="mt-6 card p-5">
              <div className="mb-3 flex items-center gap-2">
                <FlaskConical className="h-4 w-4 text-accent" />
                <div className="text-sm font-medium">Per-slice CATE</div>
                <span className="pill">{cate.n_significant} of {cate.n_slices} significant at 95%</span>
              </div>
              {cate.slices.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted">
                  No slices with ≥5 samples in both arms yet. Run more benchmarks.
                </div>
              ) : (
                <div className="space-y-1.5 text-xs">
                  <div className="grid grid-cols-12 pb-1 text-muted uppercase tracking-wider">
                    <div className="col-span-3">Cohort</div>
                    <div className="col-span-1">Ticket</div>
                    <div className="col-span-2 text-right">n agent / naive</div>
                    <div className="col-span-2 text-right">p agent / naive</div>
                    <div className="col-span-2 text-right">CATE</div>
                    <div className="col-span-2 text-right">95% CI</div>
                  </div>
                  {cate.slices.map((s) => (
                    <div key={`${s.cohort}-${s.ticket_bucket}`}
                         className="grid grid-cols-12 items-center border-t border-border py-1.5">
                      <div className="col-span-3 text-sm flex items-center gap-2">
                        {s.significant ? (
                          <CheckCircle2 className="h-3.5 w-3.5 text-good" />
                        ) : (
                          <MinusCircle className="h-3.5 w-3.5 text-muted" />
                        )}
                        {cohortLabel(s.cohort)}
                      </div>
                      <div className="col-span-1 text-xs text-muted">{s.ticket_bucket}</div>
                      <div className="col-span-2 text-right money text-muted">{s.n_agent} / {s.n_naive}</div>
                      <div className="col-span-2 text-right money">{pct(s.p_agent)} / {pct(s.p_naive)}</div>
                      <div className={`col-span-2 text-right money font-medium ${s.cate > 0 ? "text-good" : "text-muted"}`}>
                        {s.cate >= 0 ? "+" : ""}{pct(s.cate)}
                      </div>
                      <div className="col-span-2 text-right text-xs text-muted">
                        [{pct(s.ci_low)}, {pct(s.ci_high)}]
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-4 text-xs text-muted">
                <span className="text-text font-medium">Stratified ATE</span> uses cohort × ticket-bucket as pre-treatment strata (Cochran-Mantel-Haenszel weighting) to reduce variance vs the raw difference of proportions.
                Slices marked <CheckCircle2 className="inline h-3.5 w-3.5 text-good align-text-bottom" /> have a 95% CI that excludes zero — the agent's incremental causal effect is statistically distinguishable from doing nothing.
              </div>
            </div>
          </>
        )}
      </AppShell>
    );
  } catch {
    return <AppShell><ErrorState message="Backend not reachable." /></AppShell>;
  }
}

function Metric({
  label, value, sub, accent,
}: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="card p-5">
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className={`money mt-2 text-2xl font-semibold ${accent ? "text-accent" : ""}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}
