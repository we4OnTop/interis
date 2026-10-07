import { useCallback, useEffect, useState } from "react";
import { CheckCircle2Icon, CircleDashedIcon, DownloadIcon, LoaderIcon, SaveIcon, ShieldAlertIcon } from "lucide-react";

import { FolderField } from "@/components/FolderField";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { api, ApiError, type AppInfo, type FolderCheck } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";

const STATUS: Record<string, string> = {
  ready: "bereit",
  missing: "fehlt",
  outdated: "veraltet",
  incomplete: "unvollständig",
};

export function SystemPage() {
  const { notify, fail, confirm } = useFeedback();
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [dataDir, setDataDir] = useState("");
  const [modelsDir, setModelsDir] = useState("");
  const [modelsCheck, setModelsCheck] = useState<FolderCheck | null>(null);
  const [restarting, setRestarting] = useState(false);

  const load = useCallback(async () => {
    try {
      const i = await api<AppInfo>("GET", "/api/app");
      setInfo(i);
      return i;
    } catch (e) {
      fail(e);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void load().then((i) => {
      if (i) {
        setDataDir(i.data_dir ?? "");
        setModelsDir(i.models_dir ?? "");
      }
    });
  }, [load]);

  const job = info?.models_job;
  const downloading = !!job && (job.status === "queued" || job.status === "running");
  useEffect(() => {
    if (!downloading) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [downloading, load]);

  if (!info) return <LoaderIcon className="text-muted-foreground m-6 size-5 animate-spin" />;
  const models = info.models ?? [];
  const missing = models.filter((m) => m.status !== "ready");
  const changed = dataDir.trim() !== (info.data_dir ?? "") || modelsDir.trim() !== (info.models_dir ?? "");
  const current = job?.stage?.startsWith("models:") ? job.stage.slice(7) : null;

  const saveFolders = async () => {
    const ok = await confirm({
      title: "Ordner ändern?",
      description: "Interis startet danach neu. Laufende Transkriptionen bitte vorher abwarten.",
      confirm: "Speichern und neu starten",
    });
    if (!ok) return;
    try {
      const r = await api<{ restart: boolean }>("POST", "/api/app/folders", { data_dir: dataDir.trim(), models_dir: modelsDir.trim() || null, create: true });
      if (r.restart) setRestarting(true);
      else notify("Gespeichert – bitte Interis neu starten.");
    } catch (e) {
      fail(e);
    }
  };

  if (restarting)
    return (
      <div className="mx-auto mt-24 max-w-md space-y-3 text-center">
        <LoaderIcon className="text-muted-foreground mx-auto size-6 animate-spin" />
        <p>Interis startet neu …</p>
      </div>
    );

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6 pb-24">
      <h1 className="text-2xl font-semibold tracking-tight">System</h1>

      <Card className="gap-4">
        <CardHeader>
          <CardTitle>Modelle</CardTitle>
          <CardDescription>
            Ordner: <code>{info.models_dir}</code>
            {info.models_linked ? " (verknüpft)" : " (im Datenordner)"}. Jedes Modell ist auf eine feste Version festgelegt und wird
            vor jeder Nutzung per Prüfsumme kontrolliert.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="divide-y rounded-md border">
            {models.map((m) => (
              <div key={m.key} className="flex items-center gap-3 px-3 py-2 text-sm">
                {m.status === "ready" ? (
                  <CheckCircle2Icon className="text-linked size-4" />
                ) : current === m.key ? (
                  <LoaderIcon className="text-suggest size-4 animate-spin" />
                ) : (
                  <CircleDashedIcon className="text-muted-foreground size-4" />
                )}
                <span className="font-medium">{m.label}</span>
                <span className="text-muted-foreground truncate font-mono text-xs">{m.repo}</span>
                <span className="text-muted-foreground ml-auto shrink-0 text-xs">{m.size}</span>
                <Badge variant={m.status === "ready" ? "linked" : "secondary"}>{current === m.key ? "lädt …" : STATUS[m.status]}</Badge>
              </div>
            ))}
          </div>

          {downloading && (
            <div className="space-y-1.5">
              <Progress value={(job!.progress ?? 0) * 100} />
              <p className="text-muted-foreground text-xs">
                Download läuft{current && current !== "done" ? `: ${models.find((m) => m.key === current)?.label ?? current}` : ""} – das kann
                eine Weile dauern. Interis kann währenddessen benutzt werden.
              </p>
            </div>
          )}
          {job?.status === "failed" && (
            <p className="text-destructive flex items-start gap-1.5 text-sm">
              <ShieldAlertIcon className="mt-0.5 size-4 shrink-0" />
              Download fehlgeschlagen: {job.message.split("\n").pop()}
              {/firewall|10013|blocked|Network/i.test(job.message) && " – ist die Internetsperre für Interis aktiv? Für den Download kurz deaktivieren."}
            </p>
          )}
          {missing.length > 0 && !downloading && (
            <Button
              onClick={async () => {
                try {
                  await api("POST", "/api/app/models/download");
                  notify("Download gestartet");
                  await load();
                } catch (e) {
                  if (!(e instanceof ApiError && e.status === 409)) fail(e);
                }
              }}
            >
              <DownloadIcon />
              {missing.length} fehlende(s) Modell(e) herunterladen
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className="gap-4">
        <CardHeader>
          <CardTitle>Ordner</CardTitle>
          <CardDescription>Einstellungen: {info.settings_file}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label>Datenordner (Aufnahmen, Transkripte, Markierungen)</Label>
            <FolderField value={dataDir} onChange={setDataDir} purpose="data" />
          </div>
          <div className="space-y-2">
            <Label>Modell-Ordner</Label>
            <FolderField value={modelsDir} onChange={setModelsDir} purpose="models" onChecked={setModelsCheck} />
            {modelsCheck?.exists && modelsCheck.ready === 0 && modelsDir.trim() !== info.models_dir && (
              <p className="text-muted-foreground text-xs">Nach dem Wechsel können die Modelle hier heruntergeladen werden.</p>
            )}
          </div>
          <Button disabled={!changed || !dataDir.trim()} onClick={saveFolders}>
            <SaveIcon />
            Speichern und neu starten
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
