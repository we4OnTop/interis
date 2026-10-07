import { useEffect, useState } from "react";
import { AlertTriangleIcon, CheckCircle2Icon, FolderOpenIcon, LoaderIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, pickFolder, type FolderCheck } from "@/lib/api";

/** Path input with native folder dialog (desktop app) and a live check of the folder. */
export function FolderField({
  value,
  onChange,
  purpose,
  onChecked,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  purpose: "data" | "models";
  onChecked?: (c: FolderCheck | null) => void;
  placeholder?: string;
}) {
  const [check, setCheck] = useState<FolderCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const desktop = !!window.pywebview?.api;

  useEffect(() => {
    if (!value.trim()) {
      setCheck(null);
      setError(null);
      onChecked?.(null);
      return;
    }
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const c = await api<FolderCheck>("POST", `/api/app/check-folder/${purpose}`, { path: value.trim() });
        setCheck(c);
        setError(null);
        onChecked?.(c);
        if (c.path !== value.trim() && c.exists) onChange(c.path); // e.g. models found in <folder>\models
      } catch (e) {
        setCheck(null);
        setError(e instanceof Error ? e.message : String(e));
        onChecked?.(null);
      } finally {
        setBusy(false);
      }
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, purpose]);

  return (
    <div className="space-y-1.5">
      <div className="flex gap-2">
        <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="font-mono text-sm" />
        {desktop && (
          <Button
            variant="outline"
            onClick={async () => {
              const p = await pickFolder(value);
              if (p) onChange(p);
            }}
          >
            <FolderOpenIcon />
            Durchsuchen …
          </Button>
        )}
      </div>
      {busy && <LoaderIcon className="text-muted-foreground size-4 animate-spin" />}
      {error && <p className="text-destructive text-xs">{error}</p>}
      {check && !busy && (
        <div className="space-y-1 text-xs">
          {!check.exists && <p className="text-muted-foreground">Ordner existiert noch nicht – wird angelegt.</p>}
          {check.exists && purpose === "data" && (
            <p className="text-muted-foreground flex items-center gap-1">
              <CheckCircle2Icon className="text-linked size-3.5" />
              {check.has_interis ? "Enthält bereits Interis-Daten – werden weiterverwendet." : "Ordner gefunden."}
            </p>
          )}
          {check.exists && purpose === "models" && (
            <p className="flex items-center gap-1">
              {check.ready ? <CheckCircle2Icon className="text-linked size-3.5" /> : <AlertTriangleIcon className="text-suggest size-3.5" />}
              {check.ready
                ? `${check.ready} von ${check.models?.length} Modellen gefunden und vollständig.`
                : "Hier liegen noch keine Modelle – sie können hierhin heruntergeladen werden."}
            </p>
          )}
          {check.warning && (
            <p className="text-suggest flex items-start gap-1">
              <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
              {check.warning}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
