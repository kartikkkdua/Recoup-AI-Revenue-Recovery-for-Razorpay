import type { DriftAlert } from "@/lib/api";
import { cohortLabel, pct } from "@/lib/format";
import { AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";

export function DriftAlerts({ alerts }: { alerts: DriftAlert[] }) {
  if (!alerts.length) return null;
  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-yellow-400" />
        <div className="text-sm font-medium">Cohort-mix drift</div>
        <div className="text-xs text-muted">recent 6h vs 7-day baseline</div>
      </div>
      <div className="space-y-2">
        {alerts.map((a) => {
          const rising = a.delta_pp > 0;
          const color = a.severity === "critical" ? "text-red-400"
                       : a.severity === "warn" ? "text-yellow-400" : "text-muted";
          const Icon = rising ? TrendingUp : TrendingDown;
          return (
            <div key={a.cohort} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <Icon className={`h-4 w-4 ${color}`} />
                <span>{cohortLabel(a.cohort)}</span>
                <span className={`pill ${color}`}>{a.severity}</span>
              </div>
              <div className="flex items-baseline gap-3 text-xs">
                <span className="text-muted">{pct(a.baseline_share)}</span>
                <span className="text-muted">→</span>
                <span className={`money font-medium ${color}`}>{pct(a.recent_share)}</span>
                <span className={`money font-medium ${color}`}>
                  ({rising ? "+" : ""}{pct(a.delta_pp)})
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 text-xs text-muted">
        Actionable upstream: sustained rises in <span className="text-text">bank_downtime</span> often
        mean an acquirer/issuer is failing; contact your PSP.
      </div>
    </div>
  );
}
