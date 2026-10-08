import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { CircleAlertIcon, CircleCheckIcon } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";

// Small status messages ("toasts") and promise-based confirmation dialogs.

interface Toast {
  id: number;
  text: string;
  error: boolean;
}

interface ConfirmOptions {
  title: string;
  description?: string;
  confirm?: string;
  destructive?: boolean;
}

interface Feedback {
  notify: (text: string) => void;
  fail: (error: unknown) => void;
  confirm: (o: ConfirmOptions) => Promise<boolean>;
}

const Ctx = createContext<Feedback | null>(null);

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [ask, setAsk] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<(ok: boolean) => void>(() => {});
  const next = useRef(1);

  const push = useCallback((text: string, error: boolean) => {
    const id = next.current++;
    setToasts((t) => [...t.slice(-3), { id, text, error }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), error ? 8000 : 3500);
  }, []);

  // stable identity: effects that depend on notify/fail must not re-run every time a toast is added
  const value = useMemo<Feedback>(
    () => ({
      notify: (text) => push(text, false),
      fail: (e) => push(e instanceof Error ? e.message : String(e), true),
      confirm: (o) =>
        new Promise<boolean>((resolve) => {
          resolver.current = resolve;
          setAsk(o);
        }),
    }),
    [push],
  );

  const close = (ok: boolean) => {
    setAsk(null);
    resolver.current(ok);
  };

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-20 z-[60] flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cn(
              "bg-popover animate-in fade-in-0 slide-in-from-bottom-2 pointer-events-auto flex items-start gap-2 rounded-lg border p-3 text-sm shadow-lg",
              t.error && "border-destructive/40",
            )}
          >
            {t.error ? (
              <CircleAlertIcon className="text-destructive mt-0.5 size-4 shrink-0" />
            ) : (
              <CircleCheckIcon className="text-linked mt-0.5 size-4 shrink-0" />
            )}
            <span className="whitespace-pre-line">{t.text}</span>
          </div>
        ))}
      </div>
      <AlertDialog open={ask !== null} onOpenChange={(o) => !o && close(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{ask?.title}</AlertDialogTitle>
            {ask?.description && <AlertDialogDescription>{ask.description}</AlertDialogDescription>}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => close(false)}>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              className={cn(ask?.destructive && "bg-destructive hover:bg-destructive/90 text-white")}
              onClick={() => close(true)}
            >
              {ask?.confirm || "OK"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Ctx.Provider>
  );
}

export const useFeedback = () => useContext(Ctx)!;
