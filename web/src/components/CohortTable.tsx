import type { CohortRow } from "@/lib/api";
import { cohortLabel, inr, pct } from "@/lib/format";

export function CohortTable({ rows }: { rows: CohortRow[] }) {
  const max = Math.max(1, ...rows.map((r) => r.amount_paise));
  return (
    <div className="card p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <div>
          <div className="text-sm font-medium">Failure cohorts</div>
          <div className="text-xs text-muted">Where recovery revenue actually comes from</div>
        </div>
      </div>
      {rows.length === 0 ? (
        <EmptyRow />
      ) : (
        <div className="space-y-2">
          {rows.map((r) => (
            <div key={r.cohort} className="grid grid-cols-12 items-center gap-3">
              <div className="col-span-3 text-sm">{cohortLabel(r.cohort)}</div>
              <div className="col-span-5">
                <div className="h-2 w-full overflow-hidden rounded-full bg-white/5">
                  <div
                    className="h-full bg-accent"
                    style={{ width: `${(r.amount_paise / max) * 100}%` }}
                  />
                </div>
              </div>
              <div className="col-span-2 text-right money text-sm">{inr(r.amount_paise)}</div>
              <div className="col-span-2 text-right money text-sm text-good">
                {pct(r.recovery_rate)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EmptyRow() {
  return (
    <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted">
      No traffic yet. Click <span className="text-text">Run simulator</span> to seed a benchmark.
    </div>
  );
}
