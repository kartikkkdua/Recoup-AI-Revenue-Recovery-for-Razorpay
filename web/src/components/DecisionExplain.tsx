import type { DecisionContext } from "@/lib/api";
import { cohortLabel, pct } from "@/lib/format";

export function DecisionExplain({ ctx }: { ctx: DecisionContext }) {
  if (!ctx.classification) return null;
  const c = ctx.classification;
  const p = ctx.probability;
  const gate = ctx.gate_triggered;

  return (
    <div className="card p-5">
      <div className="text-xs uppercase tracking-wider text-muted">Why we did this</div>
      <div className="mt-3 space-y-2 text-sm leading-6">
        <Line>
          Classified as <b>{cohortLabel(c.cohort)}</b> by <span className="pill">{c.reasoning}</span>
          {" "}(confidence {pct(c.confidence, 0)}).
        </Line>
        {ctx.strategy_reason && (
          <Line>
            Playbook: <span className="text-text">{ctx.strategy_reason}</span>
          </Line>
        )}
        {p && (
          <Line>
            Expected recovery <b>{pct(p.learned_blended ?? p.prior ?? 0)}</b>
            {typeof p.observed_attempts === "number" && p.observed_attempts > 0 ? (
              <>
                {" "}(learned from {p.observed_attempts} prior attempts in this hour ·
                observed {pct(p.observed_p ?? 0)},
                prior {pct(p.prior ?? 0)})
              </>
            ) : (
              <> (cold start — using prior; no learned observations yet in this hour)</>
            )}.
          </Line>
        )}
        {gate && (
          <Line>
            <span className="pill text-yellow-400">gate: {gate.step}</span>{" "}
            {typeof gate.defer_hours === "number" && <>Deferred by {gate.defer_hours}h.</>}
            {gate.reason ? <> {String(gate.reason)}</> : null}
          </Line>
        )}
      </div>
    </div>
  );
}

function Line({ children }: { children: React.ReactNode }) {
  return <div className="text-muted">{children}</div>;
}
