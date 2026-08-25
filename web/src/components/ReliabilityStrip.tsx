import type { Reliability } from "@/lib/api";
import { ShieldCheck, Zap, Users } from "lucide-react";

export function ReliabilityStrip({ r }: { r: Reliability }) {
  const circuit = r.razorpay_circuit;
  const circuitColor =
    circuit.state === "closed" ? "text-good" :
    circuit.state === "half_open" ? "text-yellow-400" : "text-red-400";
  return (
    <div className="grid grid-cols-3 gap-4">
      <Cell
        icon={<ShieldCheck className="h-4 w-4" />}
        label="Duplicates dropped"
        value={r.duplicates_dropped_total.toLocaleString("en-IN")}
        sub="idempotency guard — no double-charge"
      />
      <Cell
        icon={<Users className="h-4 w-4" />}
        label="Rate-limit denials"
        value={r.rate_limiter.denials_total.toLocaleString("en-IN")}
        sub={`cap ${r.rate_limiter.max_per_customer_per_24h}/customer/24h · ${r.rate_limiter.customers_tracked} tracked`}
      />
      <Cell
        icon={<Zap className={`h-4 w-4 ${circuitColor}`} />}
        label="Razorpay circuit"
        value={circuit.state.replace("_", " ")}
        valueClass={circuitColor}
        sub={circuit.state === "open"
          ? `re-probes in ${Math.ceil(circuit.opens_remaining_s)}s`
          : `${circuit.consecutive_failures} consecutive failures`}
      />
    </div>
  );
}

function Cell({
  icon, label, value, sub, valueClass,
}: { icon: React.ReactNode; label: string; value: string; sub: string; valueClass?: string }) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted">
        {icon}
        {label}
      </div>
      <div className={`money mt-2 text-xl font-semibold ${valueClass ?? ""}`}>{value}</div>
      <div className="mt-1 text-xs text-muted">{sub}</div>
    </div>
  );
}
