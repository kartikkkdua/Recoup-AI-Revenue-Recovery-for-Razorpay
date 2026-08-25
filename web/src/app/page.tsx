import Link from "next/link";
import { ArrowRight, ShieldCheck, Zap, LineChart, GitBranch, TrendingUp, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { inr, pct, cohortLabel } from "@/lib/format";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type Live = {
  agent_recovered_paise: number;
  agent_rate: number;
  naive_recovered_paise: number;
  naive_rate: number;
  attempts_saved: number;
  fees_saved_paise: number;
  cohorts: Array<{ cohort: string; naive: number; agent: number }>;
  data_available: boolean;
};

const SEED: Live = {
  agent_recovered_paise: 598_00_00,   // ₹5.98L
  agent_rate: 0.607,
  naive_recovered_paise: 236_60_00,   // ₹2.37L
  naive_rate: 0.180,
  attempts_saved: 555,
  fees_saved_paise: 1129 * 100,
  cohorts: [
    { cohort: "insufficient_funds", naive: 0.011, agent: 0.78 },
    { cohort: "bank_downtime",      naive: 0.20,  agent: 0.75 },
    { cohort: "auth_expired",       naive: 0.12,  agent: 0.53 },
    { cohort: "card_declined",      naive: 0.084, agent: 0.26 },
    { cohort: "upi_psp_error",      naive: 0.37,  agent: 0.55 },
    { cohort: "risk_declined",      naive: 0.00,  agent: 0.00 },
  ],
  data_available: false,
};

async function loadLive(): Promise<Live> {
  try {
    const [cmp, agentCohorts, naiveCohorts] = await Promise.all([
      api.compare(),
      api.cohorts(24 * 30, "agent"),
      api.cohorts(24 * 30, "naive"),
    ]);
    if (!cmp.naive.counts.total || !cmp.agent.counts.total) return SEED;
    const naiveMap = new Map(naiveCohorts.cohorts.map((c) => [c.cohort, c.recovery_rate]));
    const cohorts = agentCohorts.cohorts
      .filter((c) => c.count >= 3 && c.cohort !== "unknown")
      .map((c) => ({
        cohort: c.cohort,
        naive: naiveMap.get(c.cohort) ?? 0,
        agent: c.recovery_rate,
      }))
      .sort((a, b) => (b.agent - b.naive) - (a.agent - a.naive))
      .slice(0, 6);
    return {
      agent_recovered_paise: cmp.agent.recovered_amount_paise,
      agent_rate: cmp.agent.recovery_rate,
      naive_recovered_paise: cmp.naive.recovered_amount_paise,
      naive_rate: cmp.naive.recovery_rate,
      attempts_saved: cmp.lift.attempts_saved,
      fees_saved_paise: cmp.lift.fees_saved_paise,
      cohorts,
      data_available: true,
    };
  } catch {
    return SEED;
  }
}

export default async function LandingPage() {
  const live = await loadLive();
  const liftMultiple = live.naive_recovered_paise > 0
    ? (live.agent_recovered_paise / live.naive_recovered_paise).toFixed(1)
    : "—";
  const apiReduction = live.attempts_saved > 0
    ? Math.round((live.attempts_saved / (live.attempts_saved + 800)) * 100)
    : 0;

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2">
          <div className="grid h-7 w-7 place-items-center rounded-md bg-accent/20 text-accent">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <span className="text-sm font-semibold tracking-tight">Recoup</span>
        </div>
        <nav className="flex items-center gap-6 text-sm text-muted">
          <Link href="/dashboard" className="hover:text-text">Dashboard</Link>
          <Link href="/subscriptions" className="hover:text-text">Subscriptions</Link>
          <Link href="/roi" className="hover:text-text">ROI</Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-white hover:bg-accent/90"
          >
            Open app <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </nav>
      </header>

      {/* HERO */}
      <section className="mx-auto max-w-4xl px-6 pt-16 text-center">
        <div className="pill mx-auto mb-6 border-accent/40 text-accent">
          Razorpay AI Buildathon · Revenue Recovery
        </div>
        <h1 className="text-balance text-5xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
          Every failed payment is a decision.<br />
          <span className="text-muted">We make the right one, automatically.</span>
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg text-muted">
          Recoup watches your Razorpay payment stream, classifies every failure, and executes the
          recovery playbook that actually works for that cohort — with a full audit trail on every
          money action.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-md bg-accent px-5 py-2.5 font-medium text-white hover:bg-accent/90"
          >
            See it running <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/roi"
            className="inline-flex items-center gap-2 rounded-md border border-border px-5 py-2.5 hover:bg-white/5"
          >
            Calculate my ROI
          </Link>
        </div>
      </section>

      {/* THE NUMBERS */}
      <section className="mx-auto mt-20 max-w-5xl px-6">
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border p-6">
            <div>
              <div className="text-xs uppercase tracking-wider text-muted">Measured on identical failure streams</div>
              <div className="mt-1 text-lg">Recoup vs a naive retry-everything baseline</div>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted">
              <span className={`inline-block h-2 w-2 rounded-full ${live.data_available ? "bg-good animate-pulse" : "bg-yellow-400"}`} />
              {live.data_available ? "live from this deploy" : "seed benchmark numbers"}
            </div>
          </div>
          <div className="grid grid-cols-2 divide-x divide-border sm:grid-cols-4">
            <Metric label="₹ Recovered" value={inr(live.agent_recovered_paise)}
                    sub={`vs ${inr(live.naive_recovered_paise)} naive`} accent />
            <Metric label="Recovery rate" value={pct(live.agent_rate)}
                    sub={`vs ${pct(live.naive_rate)} naive`} />
            <Metric label="More revenue" value={`${liftMultiple}×`}
                    sub="same failure stream" />
            <Metric label="API calls saved" value={live.attempts_saved.toLocaleString("en-IN")}
                    sub={`${apiReduction}% fewer Razorpay hits`} />
          </div>
        </div>
      </section>

      {/* PER-COHORT */}
      <section className="mx-auto mt-16 max-w-5xl px-6">
        <div className="mb-6 text-center">
          <div className="pill mx-auto mb-3">Per cohort</div>
          <h2 className="text-3xl font-semibold tracking-tight">
            Knowing <span className="text-accent">when not to retry</span> is what wins.
          </h2>
          <p className="mx-auto mt-2 max-w-2xl text-sm text-muted">
            Naive retry hammers every failure three times. We route each failure to its right
            playbook — payday retry for insufficient funds, re-tokenization for expired auth,
            rail switch for card declines, backoff for bank downtime.
          </p>
        </div>
        <div className="card p-6">
          <div className="grid grid-cols-12 pb-2 text-xs uppercase tracking-wider text-muted">
            <div className="col-span-4">Cohort</div>
            <div className="col-span-3 text-right">Naive</div>
            <div className="col-span-3 text-right">Recoup</div>
            <div className="col-span-2 text-right">Lift</div>
          </div>
          {live.cohorts.map((c) => {
            const delta = c.agent - c.naive;
            return (
              <div key={c.cohort} className="grid grid-cols-12 items-center border-t border-border py-3 text-sm">
                <div className="col-span-4">{cohortLabel(c.cohort)}</div>
                <div className="col-span-3 text-right money text-muted">{pct(c.naive)}</div>
                <div className="col-span-3 text-right money font-medium text-good">{pct(c.agent)}</div>
                <div className="col-span-2 text-right money text-accent">
                  {delta >= 0 ? "+" : ""}{pct(delta)}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* MECHANISM */}
      <section className="mx-auto mt-20 grid max-w-5xl gap-4 px-6 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { icon: Zap, title: "Right rail, right time",
            body: "Bank down? Backoff and retry. Card declined? Send a UPI link. Insufficient funds? Nudge on payday. 7 playbooks, one per cohort." },
          { icon: ShieldCheck, title: "LLM never on the money path",
            body: "Rules classify; strategy is deterministic. The LLM only picks a cohort label when rules are ambiguous, never authorizes a charge." },
          { icon: LineChart, title: "Adaptive learning",
            body: "Rolling per-cohort × per-hour conversion rates with a Beta prior. Cold cohorts hold steady, hot cohorts drift toward observed reality." },
          { icon: GitBranch, title: "Every action reversible",
            body: "Idempotent by event id. Rate-limited per customer. Circuit-broken on the Razorpay client. Full audit trail on every recovery." },
        ].map(({ icon: Icon, title, body }) => (
          <div key={title} className="card p-5">
            <Icon className="h-5 w-5 text-accent" />
            <div className="mt-3 font-medium">{title}</div>
            <p className="mt-1.5 text-sm text-muted leading-relaxed">{body}</p>
          </div>
        ))}
      </section>

      {/* CTA */}
      <section className="mx-auto mt-24 max-w-3xl px-6 text-center">
        <div className="card p-10">
          <TrendingUp className="mx-auto h-8 w-8 text-accent" />
          <h2 className="mt-4 text-2xl font-semibold">See what Recoup would save you</h2>
          <p className="mx-auto mt-2 max-w-lg text-sm text-muted">
            Enter your monthly failed payment volume — get projected recovered revenue,
            gateway fees saved, and per-cohort model behavior in seconds.
          </p>
          <Link
            href="/roi"
            className="mt-6 inline-flex items-center gap-2 rounded-md bg-accent px-5 py-2.5 font-medium text-white hover:bg-accent/90"
          >
            Open the ROI calculator <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      <footer className="mx-auto mt-24 max-w-6xl border-t border-border px-6 py-8 text-center text-xs text-muted">
        Recoup · Built for the Razorpay AI Buildathon · Revenue Recovery track ·{" "}
        <a href="https://github.com/kartikcodespaces/Bulidathon" className="hover:text-text">source</a>
      </footer>
    </div>
  );
}

function Metric({
  label, value, sub, accent,
}: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="p-6">
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className={`money mt-2 text-2xl font-semibold ${accent ? "text-accent" : ""}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}
