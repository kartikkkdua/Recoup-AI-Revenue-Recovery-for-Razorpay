"use client";

import { useEffect, useRef, useState } from "react";
import { inr, pct } from "@/lib/format";
import { Activity } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

type Tick = {
  total: number; recovered: number;
  recovered_paise: number; eligible_paise: number;
  recovery_rate: number; latest_id: number;
  duplicates_dropped: number; rate_limit_denials: number;
  circuit: string; at: string;
};

export function LiveTicker() {
  const [tick, setTick] = useState<Tick | null>(null);
  const [connected, setConnected] = useState(false);
  const prev = useRef<Tick | null>(null);
  const [pulseKey, setPulseKey] = useState(0);

  useEffect(() => {
    // Screenshot hook: `?nolive=1` disables the SSE connection so headless
    // browsers can capture a stable frame without the stream keeping the load
    // event alive forever.
    if (typeof window !== "undefined" && window.location.search.includes("nolive=1")) return;
    const es = new EventSource(`${BASE}/api/stream/live`);
    es.addEventListener("open", () => setConnected(true));
    es.addEventListener("error", () => setConnected(false));
    es.addEventListener("tick", (ev: MessageEvent) => {
      const t: Tick = JSON.parse(ev.data);
      if (prev.current && (t.total !== prev.current.total || t.recovered_paise !== prev.current.recovered_paise)) {
        setPulseKey((k) => k + 1);
      }
      prev.current = t;
      setTick(t);
    });
    return () => es.close();
  }, []);

  if (!tick) {
    return (
      <div className="card p-3 flex items-center gap-2 text-xs text-muted">
        <Activity className="h-3.5 w-3.5" />
        Connecting to live stream…
      </div>
    );
  }

  return (
    <div key={pulseKey} className="card p-3 flex items-center justify-between text-xs animate-in fade-in duration-500">
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2 w-2 rounded-full ${connected ? "bg-good animate-pulse" : "bg-red-400"}`} />
        <span className="text-muted">live</span>
        <span className="text-muted">·</span>
        <span className="money text-text">{tick.total.toLocaleString("en-IN")}</span>
        <span className="text-muted">events</span>
        <span className="text-muted">·</span>
        <span className="money text-accent">{inr(tick.recovered_paise)}</span>
        <span className="text-muted">recovered</span>
        <span className="text-muted">·</span>
        <span className="money text-good">{pct(tick.recovery_rate, 1)}</span>
      </div>
      <div className="flex items-center gap-3 text-muted">
        <span>dupes {tick.duplicates_dropped}</span>
        <span>rl-deny {tick.rate_limit_denials}</span>
        <span>circuit <span className={tick.circuit === "closed" ? "text-good" : "text-yellow-400"}>{tick.circuit}</span></span>
      </div>
    </div>
  );
}
