import { AlertTriangle } from "lucide-react";

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="card mx-auto max-w-xl p-8 text-center">
      <AlertTriangle className="mx-auto h-6 w-6 text-warn" />
      <div className="mt-3 text-sm font-medium">Something's not right</div>
      <div className="mt-1 text-sm text-muted">{message}</div>
    </div>
  );
}
