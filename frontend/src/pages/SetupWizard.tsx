import { useState } from "react";
import { DownloadIcon, LinkIcon, LoaderIcon, ShieldCheckIcon } from "lucide-react";

import { FolderField } from "@/components/FolderField";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type AppInfo, type FolderCheck } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { cn } from "@/lib/utils";

/** First start: where the interview data goes and where the models are. */
export function SetupWizard({ info }: { info: AppInfo }) {
  const { fail } = useFeedback();
  const [dataDir, setDataDir] = useState("");
  const [dataCheck, setDataCheck] = useState<FolderCheck | null>(null);
  const [mode, setMode] = useState<"link" | "download">("link");
  const [modelsDir, setModelsDir] = useState("");
  const [modelsCheck, setModelsCheck] = useState<FolderCheck | null>(null);
  const [downloadDir, setDownloadDir] = useState(info.suggested_models_dir ?? "");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  const target = mode === "link" ? modelsDir : downloadDir;
  const canSave = !!dataDir.trim() && !!dataCheck && (mode === "download" ? !!downloadDir.trim() : !!modelsCheck?.ready);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api<{ restart: boolean }>("POST", "/api/app/folders", {
        data_dir: dataDir.trim(),
        models_dir: target.trim() || null,
        create: true,
      });
      setDone(true);
      if (!r.restart) setSaving(false);
    } catch (e) {
      fail(e);
      setSaving(false);
    }
  };

  if (done)
    return (
      <div className="mx-auto mt-24 max-w-md space-y-3 text-center">
        <LoaderIcon className="text-muted-foreground mx-auto size-6 animate-spin" />
        <p>Gespeichert – Interis startet neu …</p>
        {!info.desktop && <p className="text-muted-foreground text-sm">Bitte `interis serve` neu starten.</p>}
      </div>
    );

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Willkommen bei Interis</h1>
        <p className="text-muted-foreground mt-1 flex items-center gap-1.5 text-sm">
          <ShieldCheckIcon className="size-4" />
          Zwei Ordner festlegen – danach läuft alles offline auf diesem Rechner.
        </p>
      </div>

      <Card className="gap-4">
        <CardHeader>
          <CardTitle>1. Datenordner</CardTitle>
          <CardDescription>
            Hier landen Aufnahmen, Transkripte und deine Markierungen. Am besten auf einem verschlüsselten VeraCrypt-Laufwerk, z. B.{" "}
            <code>X:\interis-data</code>. Nicht in OneDrive.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FolderField value={dataDir} onChange={setDataDir} purpose="data" onChecked={setDataCheck} placeholder="X:\interis-data" />
        </CardContent>
      </Card>

      <Card className="gap-4">
        <CardHeader>
          <CardTitle>2. Modelle (ca. 8 GB)</CardTitle>
          <CardDescription>
            Die KI-Modelle enthalten keine persönlichen Daten und können überall liegen, z. B. auf einem USB-Stick oder einem zweiten
            Laufwerk. Sie werden nur verknüpft, nicht kopiert, und vor jeder Nutzung per Prüfsumme kontrolliert.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 sm:grid-cols-2">
            <ChoiceButton active={mode === "link"} onClick={() => setMode("link")} icon={<LinkIcon />} title="Vorhandene Modelle verwenden">
              Ordner mit Modellen von einem anderen PC oder USB-Stick wählen
            </ChoiceButton>
            <ChoiceButton active={mode === "download"} onClick={() => setMode("download")} icon={<DownloadIcon />} title="Modelle herunterladen">
              Einmalig aus dem Internet laden (15–60 min) – Zielordner frei wählbar
            </ChoiceButton>
          </div>
          {mode === "link" ? (
            <FolderField value={modelsDir} onChange={setModelsDir} purpose="models" onChecked={setModelsCheck} placeholder="E:\interis-models" />
          ) : (
            <>
              <FolderField value={downloadDir} onChange={setDownloadDir} purpose="models" placeholder="D:\interis-models" />
              <p className="text-muted-foreground text-xs">
                Der Download startet nach dem Speichern auf der Seite „System“. Danach wird nichts mehr aus dem Internet geladen.
              </p>
            </>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button size="lg" disabled={!canSave || saving} onClick={save}>
          {saving && <LoaderIcon className="animate-spin" />}
          Speichern und starten
        </Button>
        <span className="text-muted-foreground text-xs">Gespeichert in {info.settings_file} – später unter „System“ änderbar.</span>
      </div>
    </div>
  );
}

function ChoiceButton({
  active,
  onClick,
  icon,
  title,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "hover:bg-accent flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-left transition-colors [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0",
        active && "border-primary ring-primary/20 ring-2",
      )}
    >
      {icon}
      <span>
        <span className="block text-sm font-medium">{title}</span>
        <span className="text-muted-foreground block text-xs">{children}</span>
      </span>
    </button>
  );
}
