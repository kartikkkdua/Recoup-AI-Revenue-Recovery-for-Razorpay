"use client";
import { useState } from "react";
import { Copy, Check } from "lucide-react";

export function CopyableRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="flex items-center justify-between rounded-md border border-border bg-black/20 px-3 py-2 text-sm">
      <div className="flex min-w-0 flex-col">
        <span className="text-xs uppercase tracking-wider text-muted">{label}</span>
        <code className="truncate">{value}</code>
      </div>
      <button onClick={copy} className="ml-3 shrink-0 rounded-md p-1.5 text-muted hover:bg-white/5 hover:text-text">
        {copied ? <Check className="h-4 w-4 text-good" /> : <Copy className="h-4 w-4" />}
      </button>
    </div>
  );
}
