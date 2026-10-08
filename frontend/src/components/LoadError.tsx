import { RefreshCwIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

/** Shown in place of a spinner when a page's first load failed. */
export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="m-4 space-y-3 p-2 text-sm sm:m-6">
      <p className="text-destructive whitespace-pre-line">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCwIcon />
        Erneut versuchen
      </Button>
    </div>
  );
}
